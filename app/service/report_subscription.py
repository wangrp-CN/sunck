"""定期订阅推送服务（模块①·报告与触达增强）。

职责：
- ``is_due``：判定某订阅在给定时刻是否「到点」（按 frequency + 北京时 send_hour/day，
  且本周期尚未运行过）。
- ``run_one``：为单个订阅生成报告并经通知中心触达（报告按订阅人自身数据范围生成）。
- ``run_due_subscriptions``：扫描全部启用订阅，对到点者逐一运行（调度进程调用）。
- CRUD 辅助供路由层使用。

调度语义：``send_hour`` 取**北京时**（与全站业务时区一致）；``run_due_subscriptions``
由定时脚本（deploy 提供的 hourly timer）每小时调用一次即可——因 ``last_run_at`` 已记录
本周期运行时刻，天然幂等，不会同周期重复下发。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import LOCAL_TZ
from app.core.data_scope import resolve_data_scope
from app.core.exceptions import BusinessError
from app.core.notify import notify
from app.model.project import Project
from app.model.report_subscription import (
    FREQ_MONTHLY,
    FREQ_WEEKLY,
    ReportSubscription,
)
from app.model.system import User
from app.service.effectiveness_export import generate_effectiveness_report


def _period_start(nl: datetime, frequency: str) -> datetime:
    """当前周期起点（北京时，零点）。"""
    base = nl.replace(hour=0, minute=0, second=0, microsecond=0)
    if frequency == FREQ_WEEKLY:
        # 回退到本周一
        return base - timedelta(days=nl.weekday())
    if frequency == FREQ_MONTHLY:
        return base.replace(day=1)
    return base  # daily


def is_due(sub: ReportSubscription, now: datetime | None = None) -> bool:
    """判定订阅在 ``now``（默认 UTC 当前时刻）是否到点。

    - send_hour 按北京时比对；
    - weekly 需星期匹配 send_weekday；monthly 需日期匹配 send_day；
    - 已在本周期运行过（last_run_at >= 周期起点）则视为未到点，避免重复。
    """
    if not sub.enabled:
        return False
    now = now or datetime.now(timezone.utc)
    nl = now.astimezone(LOCAL_TZ)
    if nl.hour != sub.send_hour:
        return False
    if sub.frequency == FREQ_WEEKLY and nl.weekday() != sub.send_weekday:
        return False
    if sub.frequency == FREQ_MONTHLY and nl.day != sub.send_day:
        return False
    ps = _period_start(nl, sub.frequency)
    if sub.last_run_at is not None and sub.last_run_at >= ps:
        return False
    return True


def run_one(db: Session, sub: ReportSubscription, now: datetime | None = None) -> dict[str, Any]:
    """为单个订阅生成报告并触达，更新运行记录。返回运行摘要。

    报告按**订阅人自身数据范围**生成（不越权）；触达经通知中心 NOTIFIERS
    （in_app 真实，sms/voice 预留）。通知内携带下载深链，点击后按需即时重生报告。
    """
    now = now or datetime.now(timezone.utc)
    user = db.get(User, sub.user_id)
    if not user:
        raise BusinessError("订阅归属用户不存在或已删除", code=400)

    scope = resolve_data_scope(user, db)
    content, filename, media_type = generate_effectiveness_report(
        db, scope, days=sub.days, fmt=sub.fmt, project_id=sub.project_id
    )

    link = f"/api/v1/subscriptions/{sub.id}/download"
    title = f"您的效能运营报告已生成（{sub.name}）"
    content_text = (
        f"统计窗口：近 {sub.days} 天 · 格式：{sub.fmt.upper()} · "
        f"点击前往下载（即时按您的数据范围重生）"
    )
    channels = sub.channels or ["in_app"]
    notify(
        db,
        [sub.user_id],
        title,
        content=content_text,
        link=link,
        category="report",
        channels=tuple(channels),
    )

    sub.last_run_at = now
    sub.last_status = "ok"
    sub.last_error = None
    return {
        "id": sub.id,
        "status": "ok",
        "bytes": len(content),
        "media_type": media_type,
        "filename": filename,
    }


def run_due_subscriptions(db: Session, now: datetime | None = None) -> list[dict[str, Any]]:
    """扫描全部启用订阅，对到点者运行并触达。每个订阅独立事务，单条失败不影响其他。

    返回 ``[{id, status, ...}, ...]``，status ∈ ok|failed。
    """
    now = now or datetime.now(timezone.utc)
    subs = db.scalars(select(ReportSubscription).where(ReportSubscription.enabled.is_(True))).all()
    results: list[dict[str, Any]] = []
    for sub in subs:
        if not is_due(sub, now):
            continue
        try:
            summary = run_one(db, sub, now)
            db.commit()
            results.append({**summary, "status": "ok"})
        except Exception as e:  # noqa: BLE001 — 单条失败需隔离，记录后继续
            db.rollback()
            sub.last_run_at = now
            sub.last_status = "failed"
            sub.last_error = str(e)[:500]
            try:
                db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
            results.append({"id": sub.id, "status": "failed", "error": str(e)[:200]})
    return results


# ---------------------------------------------------------------------------
# CRUD 辅助
# ---------------------------------------------------------------------------
def validate_project(db: Session, project_id: int | None) -> None:
    """聚焦项目必须存在且未删除，否则抛 BusinessError（避免外键/越权报错）。"""
    if project_id is None:
        return
    proj = db.get(Project, project_id)
    if proj is None or getattr(proj, "is_deleted", False):
        raise BusinessError(f"聚焦项目不存在或已删除（project_id={project_id}）", code=400)


def get_owned_or_404(db: Session, sub_id: int, current_user: User, allow_super: bool = True):
    """取订阅；不存在返回 None；非归属且（不允许超管或当前非超管）时返回 None（404 语义）。"""
    sub = db.get(ReportSubscription, sub_id)
    if sub is None:
        return None
    if sub.user_id == current_user.id:
        return sub
    if allow_super and current_user.is_superuser:
        return sub
    return None


def create_subscription(
    db: Session, current_user: User, payload: dict[str, Any]
) -> ReportSubscription:
    validate_project(db, payload.get("project_id"))
    channels = payload.get("channels") or ["in_app"]
    if isinstance(channels, str):
        try:
            channels = json.loads(channels)
        except (json.JSONDecodeError, TypeError):
            channels = ["in_app"]
    sub = ReportSubscription(
        user_id=current_user.id,
        name=payload["name"],
        fmt=payload.get("fmt", "excel"),
        days=payload.get("days", 30),
        project_id=payload.get("project_id"),
        frequency=payload.get("frequency", "daily"),
        send_hour=payload.get("send_hour", 8),
        send_weekday=payload.get("send_weekday", 0),
        send_day=payload.get("send_day", 1),
        channels=channels,
        enabled=payload.get("enabled", True),
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def update_subscription(
    db: Session, sub: ReportSubscription, payload: dict[str, Any]
) -> ReportSubscription:
    if "project_id" in payload:
        validate_project(db, payload["project_id"])
        sub.project_id = payload["project_id"]
    if "name" in payload:
        sub.name = payload["name"]
    if "fmt" in payload:
        sub.fmt = payload["fmt"]
    if "days" in payload:
        sub.days = payload["days"]
    if "frequency" in payload:
        sub.frequency = payload["frequency"]
    if "send_hour" in payload:
        sub.send_hour = payload["send_hour"]
    if "send_weekday" in payload:
        sub.send_weekday = payload["send_weekday"]
    if "send_day" in payload:
        sub.send_day = payload["send_day"]
    if "enabled" in payload:
        sub.enabled = payload["enabled"]
    if "channels" in payload:
        channels = payload["channels"]
        if isinstance(channels, str):
            try:
                channels = json.loads(channels)
            except (json.JSONDecodeError, TypeError):
                channels = ["in_app"]
        sub.channels = channels
    db.commit()
    db.refresh(sub)
    return sub


def delete_subscription(db: Session, sub: ReportSubscription) -> None:
    db.delete(sub)
    db.commit()

"""视频通道/AI 事件服务层（P3·⑧ PoC）。

- 通道台账 CRUD（数据隔离 VIA_PROJECT，channel_no 全局唯一）。
- 事件回推：按 channel_no 找通道→留痕→（ai_enabled 才接受）。
- 事件按通道可见性过滤（通道可见即事件可见）。
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.clock import now_local
from app.core.constants import ALARM_STATUS_START
from app.core.data_scope import DataScope, apply_data_scope
from app.core.exceptions import BusinessError
from app.model.alarm import Alarm
from app.model.project import Project
from app.model.video import VideoChannel, VideoEvent
from app.schema.video import (
    VIDEO_EVENT_TYPE_LABELS,
    VIDEO_EVENT_TYPES,
    VideoChannelOut,
    VideoEventOut,
)
from app.service.alarm_service import create_alarm

logger = logging.getLogger(__name__)

# 事件类型 → 告警级别（深化⑧：视频AI事件升级为平台告警）
VIDEO_EVENT_ALARM_LEVEL = {
    "intrusion": "严重",
    "smoke_fire": "严重",
    "no_helmet": "警告",
    "other": "提示",
}
# 满足自动升级的高危类型（低危 other 不自动升级，避免噪声）
VIDEO_AUTO_ESCALATE_TYPES = {"intrusion", "smoke_fire", "no_helmet"}
# 高置信度（无论类型）至少提升到「严重」
VIDEO_HIGH_CONF = 0.9


def to_channel_out(db: Session, c: VideoChannel) -> VideoChannelOut:
    project_name = None
    if c.project_id is not None:
        proj = db.get(Project, c.project_id)
        project_name = proj.name if proj else None
    out = VideoChannelOut.model_validate(c)
    out.project_name = project_name
    return out


def to_event_out(e: VideoEvent) -> VideoEventOut:
    out = VideoEventOut.model_validate(e)
    if e.channel is not None:
        out.channel_name = e.channel.name
        out.channel_no = e.channel.channel_no
    out.event_type_label = VIDEO_EVENT_TYPE_LABELS.get(e.event_type, e.event_type)
    return out


def _channel_stmt(scope: DataScope):
    return apply_data_scope(
        select(VideoChannel).where(VideoChannel.is_deleted.is_(False)), VideoChannel, scope
    )


def list_channels(
    db: Session,
    scope: DataScope,
    project_id: int | None = None,
    keyword: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[int, list[VideoChannel]]:
    stmt = _channel_stmt(scope)
    if project_id is not None:
        stmt = stmt.where(VideoChannel.project_id == project_id)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(VideoChannel.name.ilike(like) | VideoChannel.channel_no.ilike(like))
    stmt = stmt.order_by(VideoChannel.id.desc())
    rows = db.scalars(stmt).all()
    total = len(rows)
    start = max(0, (page - 1) * size)
    return total, rows[start : start + size]


def get_channel(db: Session, channel_id: int, scope: DataScope) -> VideoChannel | None:
    return db.scalar(_channel_stmt(scope).where(VideoChannel.id == channel_id))


def create_channel(db: Session, data: dict, user_id: int | None) -> VideoChannel:
    channel_no = (data.get("channel_no") or "").strip()
    if not channel_no:
        raise BusinessError("通道编号不能为空", code=400)
    dup = db.scalar(
        select(VideoChannel).where(
            VideoChannel.channel_no == channel_no, VideoChannel.is_deleted.is_(False)
        )
    )
    if dup:
        raise BusinessError(f"通道编号已存在：{channel_no}", code=400)
    c = VideoChannel(**data)
    c.created_by = user_id
    db.add(c)
    db.flush()
    return c


def update_channel(
    db: Session, channel_id: int, data: dict, scope: DataScope
) -> VideoChannel | None:
    c = get_channel(db, channel_id, scope)
    if c is None:
        return None
    for k, v in data.items():
        if v is not None:
            setattr(c, k, v)
    db.flush()
    return c


def delete_channel(db: Session, channel_id: int, scope: DataScope) -> bool:
    c = get_channel(db, channel_id, scope)
    if c is None:
        return False
    c.is_deleted = True
    db.flush()
    return True


def ingest_event(db: Session, data: dict) -> VideoEvent:
    """外部推理服务回推事件：按 channel_no 定位通道并留痕。

    - 通道不存在/已删 → 404 业务错误；ai_enabled=False → 400（提示先启用）。
    - event_type 不在枚举 → 归入 other 并保留原值到 detail 前缀。
    """
    channel_no = (data.get("channel_no") or "").strip()
    channel = db.scalar(
        select(VideoChannel).where(
            VideoChannel.channel_no == channel_no, VideoChannel.is_deleted.is_(False)
        )
    )
    if channel is None:
        raise BusinessError(f"视频通道不存在：{channel_no}", code=404)
    if not channel.ai_enabled:
        raise BusinessError(f"通道未启用AI分析：{channel_no}", code=400)

    event_type = data.get("event_type") or "other"
    detail = data.get("detail")
    if event_type not in VIDEO_EVENT_TYPES:
        detail = f"[原始类型:{event_type}] {detail or ''}".strip()
        event_type = "other"

    e = VideoEvent(
        channel_id=channel.id,
        project_id=channel.project_id,
        event_type=event_type,
        confidence=data.get("confidence"),
        snapshot_url=data.get("snapshot_url"),
        event_time=data.get("event_time") or now_local(),
        detail=detail,
        handled=False,
    )
    db.add(e)
    db.flush()

    # 深化⑧：高置信/高危事件在回推时自动升级为平台告警（开关受控，独立手动升级之外）
    if (
        settings.video_auto_escalate_enabled
        and event_type in VIDEO_AUTO_ESCALATE_TYPES
        and (e.confidence is None or e.confidence >= settings.video_auto_escalate_threshold)
    ):
        sp = db.begin_nested()
        try:
            escalate_event_to_alarm(db, e.id, scope=None)
            sp.commit()
        except Exception:  # noqa: BLE001
            sp.rollback()
            logger.warning("视频事件自动升级失败（不影响事件回推）", exc_info=True)

    return e


def escalate_event_to_alarm(
    db: Session,
    event_id: int,
    scope: DataScope | None = None,
) -> tuple[VideoEvent, Alarm | None]:
    """将视频 AI 事件升级为平台告警（深化⑧），回填 ``event.alarm_id``。

    - 幂等：``event.alarm_id`` 已存在则直接返回既有告警，不重复建单。
    - ``scope=None`` 时（外部 ingest 自动升级）跳过通道可见性校验，按全局定位。
    - 经 ``create_alarm`` 走平台统一告警去重；若命中去重锚点（并发/重复上报），
      回退查询最近一条同键告警并回填，保证联动链路闭合。
    返回 ``(event, alarm|None)``；``alarm`` 为 ``None`` 仅发生在去重命中且锚点已不存在的极端情况。
    """
    e = db.get(VideoEvent, event_id)
    if e is None:
        raise BusinessError("视频事件不存在", code=404)
    channel = db.get(VideoChannel, e.channel_id)
    if channel is None:
        raise BusinessError("事件所属通道不存在", code=404)
    if scope is not None:
        # 手动升级须落在可见通道范围内
        if get_channel(db, e.channel_id, scope) is None:
            raise BusinessError("事件不存在或无权访问", code=404)

    if e.alarm_id is not None:
        return e, db.get(Alarm, e.alarm_id)

    label = VIDEO_EVENT_TYPE_LABELS.get(e.event_type, e.event_type)
    base_level = VIDEO_EVENT_ALARM_LEVEL.get(e.event_type, "警告")
    level = base_level
    if e.confidence is not None and e.confidence >= VIDEO_HIGH_CONF and base_level != "严重":
        level = "严重"

    info = f"[视频AI] {label}：{channel.name}({channel.channel_no}) 检测到{label}"
    if e.confidence is not None:
        info += f"，置信度 {e.confidence * 100:.0f}%"
    if e.detail:
        info += f"。{e.detail}"
    if len(info) > 500:
        info = info[:497] + "..."

    alarm_type = f"视频AI-{label}"
    fields = dict(
        project_id=e.project_id,
        alarm_type=alarm_type,
        device_type="视频通道",
        device_name=channel.name,
        device_no=channel.channel_no,
        alarm_info=info,
        alarm_status=ALARM_STATUS_START,
        alarm_level=level,
        handle_status="待处理",
        alarm_time=e.event_time or now_local(),
        media_urls=e.snapshot_url,
    )
    alarm = create_alarm(db, **fields)
    if alarm is None:
        # 去重命中：回退查找最近一条同键告警作为锚点
        anchor = db.scalar(
            select(Alarm)
            .where(
                Alarm.project_id == e.project_id,
                Alarm.device_no == channel.channel_no,
                Alarm.alarm_type == alarm_type,
                Alarm.alarm_status == ALARM_STATUS_START,
            )
            .order_by(Alarm.id.desc())
        )
        alarm = anchor
    if alarm is not None:
        e.alarm_id = alarm.id
        db.flush()
    return e, alarm


def list_events(
    db: Session,
    scope: DataScope,
    channel_id: int | None = None,
    project_id: int | None = None,
    event_type: str | None = None,
    handled: bool | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[int, list[VideoEvent]]:
    """事件列表：按可见通道过滤（通道可见即事件可见）。"""
    visible_channel_ids = db.scalars(_channel_stmt(scope).with_only_columns(VideoChannel.id)).all()
    if not visible_channel_ids:
        return 0, []
    stmt = select(VideoEvent).where(VideoEvent.channel_id.in_(visible_channel_ids))
    if channel_id is not None:
        stmt = stmt.where(VideoEvent.channel_id == channel_id)
    if project_id is not None:
        stmt = stmt.where(VideoEvent.project_id == project_id)
    if event_type:
        stmt = stmt.where(VideoEvent.event_type == event_type)
    if handled is not None:
        stmt = stmt.where(VideoEvent.handled.is_(handled))
    stmt = stmt.order_by(VideoEvent.id.desc())
    rows = db.scalars(stmt).all()
    total = len(rows)
    start = max(0, (page - 1) * size)
    return total, rows[start : start + size]


def handle_event(db: Session, event_id: int, scope: DataScope) -> VideoEvent:
    """标记事件已处理（须在可见通道范围内）。"""
    e = db.get(VideoEvent, event_id)
    if e is None:
        raise BusinessError("事件不存在", code=404)
    channel = get_channel(db, e.channel_id, scope)
    if channel is None:
        raise BusinessError("事件不存在或无权访问", code=404)
    e.handled = True
    db.flush()
    return e

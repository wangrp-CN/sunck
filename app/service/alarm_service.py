"""告警服务：告警去重创建、查询、处置，以及 WebSocket 序列化。

去重（防告警风暴）：基于 Redis 的 dedup 键，同一 (设备, 类型, 围栏, 状态) 在
ALARM_DEDUP_TTL 秒内只产生一条「打开中」告警，后续重复上报被合并。
"""

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, literal, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.core.constants import (
    ALARM_STATUS_CLEARED,
    ALARM_STATUS_END,
    ALARM_STATUS_START,
    ALARM_TYPE_DEVICE,
    ALARM_TYPE_DISTANCE,
    ALARM_TYPE_FENCE,
    ALARM_TYPE_PREVENTIVE,
    ALARM_TYPE_TRAIN,
)
from app.core.data_scope import DataScope, apply_data_scope
from app.core.metrics import ALARM_CREATED_TOTAL
from app.core.redis import get_redis_client
from app.model.alarm import Alarm

logger = logging.getLogger("rail_monitor.alarm")

# 告警级别映射：围栏侵入最严重，间距过近次之，列车接近严重，设备自报告警提示级
_LEVEL_BY_TYPE: dict[str, str] = {
    ALARM_TYPE_FENCE: "严重",
    ALARM_TYPE_DISTANCE: "警告",
    ALARM_TYPE_TRAIN: "严重",
    ALARM_TYPE_DEVICE: "提示",
}

#: 同一告警的合并窗口（秒），来自配置 alarm_suppress_window_seconds（默认 300）。
ALARM_DEDUP_TTL = settings.alarm_suppress_window_seconds

#: 风暴抑制日计数 Redis 键前缀（按 UTC 日期分桶，便于跨时区统计当天抑制量）。
_STORM_KEY_PREFIX = "alarm:storm:suppressed:"


def _dedup_key(
    alarm_type: str,
    device_no: str,
    fence_name: str | None,
    alarm_status: str,
    work_plan_id: int | None = None,
) -> str:
    fence = fence_name or ""
    plan = work_plan_id if work_plan_id is not None else ""
    return f"alarm:dedup:{device_no}:{alarm_type}:{fence}:{alarm_status}:{plan}"


#: 对外暴露去重键构造（pipeline 用于生命周期配对），与内部 _dedup_key 同源。
dedup_key = _dedup_key


def create_alarm(db: Session, **fields) -> Alarm | None:
    """创建告警（带去重）。已存在合并窗口内的同类告警则返回 None。

    去重续期：命中已存在键时不只跳过，而是刷新其 TTL。这样持续违规期间
    每次上行都会续期，整个违规周期只产生「1 条」告警开始，根除「每隔
    ALARM_DEDUP_TTL 秒重复生成告警开始、无界堆积」的隐患。

    策略接入（🅱 M4，AlarmPolicy）：
    - **收敛**：命中策略配置 ``suppress_window_seconds`` 时覆盖全局合并窗口；
    - **静默抑制**：静默时段内告警仍**正常落库**（不丢数据），仅跳过站内信通知；
    - 策略解析任何异常均降级为「无策略」，绝不阻塞告警主链路。
    """
    alarm_type = fields.get("alarm_type")
    device_no = fields.get("device_no")
    fence_name = fields.get("fence_name")
    alarm_status = fields.get("alarm_status") or ALARM_STATUS_START
    work_plan_id = fields.get("work_plan_id")

    # 策略解析（收敛窗口覆盖 + 静默判定）；失败降级 None 不影响主链路
    policy = None
    try:
        from app.service import alarm_policy_service as policy_svc

        policy = policy_svc.resolve_policy(db, fields.get("project_id"), alarm_type)
    except Exception:  # noqa: BLE001
        logger.warning("告警策略解析失败，按无策略处理（不影响告警落库）")
    ttl = ALARM_DEDUP_TTL
    if policy is not None:
        try:
            from app.service import alarm_policy_service as policy_svc

            ttl = policy_svc.effective_suppress_window(policy) or ALARM_DEDUP_TTL
        except Exception:  # noqa: BLE001
            ttl = ALARM_DEDUP_TTL

    r = get_redis_client()
    key = _dedup_key(alarm_type, device_no, fence_name, alarm_status, work_plan_id)
    # 原子抢占去重槽：set(nx=True) 在 Redis 端原子完成「判断 + 占位」，
    # 彻底杜绝并发下 `exists` → `set` 的竞态双写（#8）。并发只有一方能 nx 成功。
    try:
        claimed = bool(r.set(key, "pending", nx=True, ex=ttl))
    except Exception:  # noqa: BLE001
        # Redis 不可用时降级为直接创建（与历史行为一致：宁可产生重复也不丢告警）
        logger.warning("告警去重键抢占失败，降级为直接创建：%s", key)
        claimed = True
    if not claimed:
        # 去重命中：刷新合并窗口，避免持续违规时不断重建告警
        try:
            r.expire(key, ttl)
        except Exception:  # noqa: BLE001
            logger.warning("告警去重键续期失败（不影响落库）")
        # 风暴抑制 v2：把被合并的重复告警计数累加到 anchor 告警，并累计当日抑制总量，
        # 便于值班人员感知「本窗已压制多少重复噪声」而非彻底无感丢弃。
        _count_suppressed(r, key, db)
        logger.debug("告警去重命中，跳过并续期：%s", key)
        return None

    media = fields.get("media_urls")
    if isinstance(media, (list, tuple, dict)):
        media = json.dumps(media, ensure_ascii=False)
    alarm = Alarm(
        project_id=fields.get("project_id"),
        work_plan_id=work_plan_id,
        alarm_type=alarm_type,
        device_type=fields.get("device_type"),
        device_name=fields.get("device_name"),
        device_no=device_no,
        alarm_info=fields.get("alarm_info"),
        alarm_status=alarm_status,
        alarm_level=fields.get("alarm_level") or _LEVEL_BY_TYPE.get(alarm_type or "", "警告"),
        handle_status="待处理",
        handle_content=fields.get("handle_content"),
        alarm_time=fields.get("alarm_time") or datetime.now(timezone.utc),
        fence_name=fence_name,
        media_urls=media,
    )
    db.add(alarm)
    db.flush()
    ALARM_CREATED_TOTAL.labels(alarm_type=alarm_type, alarm_level=alarm.alarm_level).inc()
    # 占位成功后写入真实告警 id（供规则引擎配对自动结束时读取），仅当槽位仍存在时覆盖
    try:
        r.set(key, str(alarm.id), xx=True, ex=ttl)
    except Exception:  # noqa: BLE001
        logger.warning("告警去重键写入失败（不影响落库）")
    # 静默抑制（🅱 M4）：静默时段内告警已正常落库，仅跳过通知打扰
    silenced = False
    if policy is not None:
        try:
            from app.service import alarm_policy_service as policy_svc

            silenced = policy_svc.in_silence(policy)
        except Exception:  # noqa: BLE001
            silenced = False
    if silenced:
        logger.info("告警 #%s 落库成功，命中策略「%s」静默时段，跳过通知", alarm.id, policy.name)
        return alarm
    # 新告警产生 → 推送站内信（去重命中时 create_alarm 已提前返回，不会重复通知）
    try:
        from app.core.notify import notify_alarm_raised

        notify_alarm_raised(db, alarm)
    except Exception:  # noqa: BLE001
        logger.warning("告警站内信通知失败（不影响告警落库）")
    return alarm


def _count_suppressed(r, key: str, db: Session) -> None:
    """去重命中时累加 anchor 的 suppressed_count，并累计当日抑制总量（风暴抑制 v2）。

    - anchor id 由 create_alarm 在占位成功后以 ``xx=True`` 写入 Redis 值；
      此处读取后对 anchor 行做服务端自增（无需先 SELECT，避免高频风暴下的额外读）。
    - 当日抑制量写入 ``alarm:storm:suppressed:{UTC日期}``（INCR，2 天 TTL），
      供 ``/metrics/alarm-storm`` 直接读取，无需扫表。
    - 任何 Redis/DB 异常均降级忽略（宁可产生重复计数，也不阻塞主告警落库）。
    """
    now = datetime.now(timezone.utc)
    try:
        raw = r.get(key)
        if raw:
            try:
                anchor_id = int(raw)
            except (TypeError, ValueError):
                anchor_id = None
            if anchor_id:
                db.execute(
                    update(Alarm)
                    .where(Alarm.id == anchor_id)
                    .values(
                        suppressed_count=Alarm.suppressed_count + 1,
                        last_suppressed_at=now,
                    )
                )
    except Exception:  # noqa: BLE001
        logger.warning("anchor 抑制计数自增失败（不影响告警落库）")
    try:
        day_key = f"{_STORM_KEY_PREFIX}{now.strftime('%Y-%m-%d')}"
        r.incr(day_key)
        r.expire(day_key, 86400 * 2)
    except Exception:  # noqa: BLE001
        logger.warning("当日抑制计数累加失败（不影响告警落库）")


def storm_suppressed_today() -> int:
    """返回当日（UTC 日期）被风暴抑制合并掉的重复告警总数。"""
    r = get_redis_client()
    try:
        day_key = f"{_STORM_KEY_PREFIX}{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        val = r.get(day_key)
        return int(val) if val else 0
    except Exception:  # noqa: BLE001
        logger.warning("读取当日抑制计数失败")
        return 0


def end_alarm_by_id(db: Session, alarm_id: int) -> bool:
    """将仍打开的告警自动置为「告警结束」（违规条件解除）。

    仅对状态仍为「告警开始」且未被人工处置的告警生效，避免重复改写或
    覆盖人工处置结果。返回是否实际更新。
    """
    alarm = db.get(Alarm, alarm_id)
    if alarm is None:
        return False
    if alarm.alarm_status == ALARM_STATUS_END or alarm.handle_status == ALARM_STATUS_CLEARED:
        return False
    alarm.alarm_status = ALARM_STATUS_END
    alarm.handle_status = ALARM_STATUS_CLEARED
    db.flush()
    return True


def reconcile_active_alarms(
    db: Session, device_no: str, current_violations: dict[str, int]
) -> list[int]:
    """根据本轮仍活跃的违规键，自动结束已解除的告警，返回被结束的告警 id 列表。

    - current_violations: {violation_key: 仍活跃告警的 open_alarm_id}
    - 上一轮记录在 Redis 哈希 rule2:active:{device_no}；本轮缺失的键即「违规已解除」，
      对其 open_alarm_id 调用 end_alarm_by_id 置「告警结束」。
    - 结束后用本轮 current_violations 重写该哈希（带 TTL），无活跃则删除。
    """
    r = get_redis_client()
    hkey = f"rule2:active:{device_no}"
    prev = r.hgetall(hkey)  # {violation_key: alarm_id_str}
    ended_ids: list[int] = []
    for vk, aid in prev.items():
        if vk not in current_violations:
            try:
                aid_int = int(aid)
            except (TypeError, ValueError):
                continue
            if end_alarm_by_id(db, aid_int):
                ended_ids.append(aid_int)
    if current_violations:
        try:
            r.hset(hkey, mapping={k: str(v) for k, v in current_violations.items()})
            r.expire(hkey, ALARM_DEDUP_TTL + 60)
        except Exception:  # noqa: BLE001
            logger.warning("活跃违规集合写入失败（不影响告警落库）")
    else:
        try:
            r.delete(hkey)
        except Exception:  # noqa: BLE001
            logger.warning("活跃违规集合清理失败（不影响告警落库）")
    return ended_ids


def _parse_media(media: Any) -> list[str]:
    """media_urls 在库中存为 JSON 字符串，对外统一解析为列表。"""
    if media is None:
        return []
    if isinstance(media, (list, tuple)):
        return [str(x) for x in media]
    if isinstance(media, str):
        s = media.strip()
        if not s:
            return []
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except (ValueError, TypeError):
            pass
        return [s]
    return []


def to_alarm_out(alarm: Alarm) -> dict[str, Any]:
    """序列化为对外/WebSocket 字典。"""
    return {
        "id": alarm.id,
        "project_id": alarm.project_id,
        "alarm_type": alarm.alarm_type,
        "device_type": alarm.device_type,
        "device_name": alarm.device_name,
        "device_no": alarm.device_no,
        "alarm_info": alarm.alarm_info,
        "alarm_status": alarm.alarm_status,
        "alarm_level": alarm.alarm_level,
        "handle_status": alarm.handle_status,
        "handle_content": alarm.handle_content,
        "fence_name": alarm.fence_name,
        "media_urls": _parse_media(alarm.media_urls),
        "work_plan_id": alarm.work_plan_id,
        "hazard_id": alarm.hazard_id,
        "suppressed_count": alarm.suppressed_count or 0,
        "alarm_time": alarm.alarm_time.isoformat() if alarm.alarm_time else None,
    }


def _alarm_list_stmt(
    scope: DataScope,
    project_id: int | None = None,
    alarm_type: str | None = None,
    handle_status: str | None = None,
    alarm_status: str | None = None,
    device_no: str | None = None,
):
    """构建告警列表/计数共用的过滤后查询（含部门数据隔离），供 list/count 复用。"""
    stmt = select(Alarm)
    stmt = apply_data_scope(stmt, Alarm, scope)
    if project_id is not None:
        stmt = stmt.where(Alarm.project_id == project_id)
    if alarm_type is not None:
        stmt = stmt.where(Alarm.alarm_type == alarm_type)
    if handle_status is not None:
        stmt = stmt.where(Alarm.handle_status == handle_status)
    if alarm_status is not None:
        stmt = stmt.where(Alarm.alarm_status == alarm_status)
    if device_no:
        stmt = stmt.where(Alarm.device_no == device_no)
    return stmt


def _preventive_metric_of(device_no: str | None) -> str | None:
    """从预防式告警的 device_no（preventive:{metric}:{ref_id}:{horizon}）解析指标 key。"""
    if not device_no or not device_no.startswith("preventive:"):
        return None
    parts = device_no.split(":")
    # preventive:{metric}:{ref_id}:{horizon_days}
    return parts[1] if len(parts) > 1 else None


def summarize_preventive(
    db: Session,
    scope: DataScope,
    project_id: int | None = None,
) -> dict[str, Any]:
    """预防式告警活跃汇总（大屏卡）：数据隔离下，统计 handle_status=待处理 的预防式预警。

    - total: 活跃总数
    - by_metric: 按指标（risk_index/health_score...）分布
    - by_level: 按告警级别分布
    - recent: 最近 5 条（含结构化字段，供前端点击下钻）
    """
    base = _alarm_list_stmt(
        scope,
        project_id=project_id,
        alarm_type=ALARM_TYPE_PREVENTIVE,
        handle_status="待处理",
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(base.with_only_columns(Alarm.device_no, Alarm.alarm_level)).all()
    by_metric: dict[str, int] = {}
    by_level: dict[str, int] = {}
    for dn, lvl in rows:
        m = _preventive_metric_of(dn)
        if m:
            by_metric[m] = by_metric.get(m, 0) + 1
        if lvl:
            by_level[lvl] = by_level.get(lvl, 0) + 1
    recent = [
        to_alarm_out(a) for a in db.scalars(base.order_by(Alarm.alarm_time.desc()).limit(5)).all()
    ]
    return {
        "total": total,
        "by_metric": by_metric,
        "by_level": by_level,
        "recent": recent,
    }


#: 告警级别固定顺序（趋势堆叠面积 / 分布 chip 共用）
_ALARM_LEVEL_ORDER = ("严重", "警告", "提示")


def situation_summary(
    db: Session,
    scope: DataScope,
    project_id: int | None = None,
    days: int = 14,
) -> dict[str, Any]:
    """告警态势总览（大屏卡）：KPI + 近 days 天按级别每日趋势，施加部门数据隔离。

    - kpi.today_new:        今日(按 date(alarm_time)=date(now))新增告警
    - kpi.pending:          待处理总数
    - kpi.pending_critical: 待处理且级别=严重（高亮红）
    - kpi.active_preventive:活跃预防式告警(待处理)
    - pending_by_level:     待处理按级别分布
    - trend:                近 days 天每日 {date,total,严重,警告,提示}

    全部复用 _alarm_list_stmt 的过滤 + 隔离，零新增迁移；趋势按 DB date() 分组，
    跨 Postgres/SQLite 一致（边界 tz 误差 ≤1 天，对 N 天趋势视图可忽略）。
    """
    days = max(1, min(int(days), 90))

    # —— 趋势：近 days 天，按日期 + 级别分组（SQL 聚合，轻量） ——
    # 以「会话本地日期」为窗口基准：func.date(alarm_time) 在 PG 中按会话时区
    # （生产为中国 +8）取日期，若桶键用 UTC 零点的 start_dt 推算，会出现近 1 天
    # 告警（如 23:xx UTC = 次日中国）落入窗口外被漏计。统一用本地日期口径对齐。
    local_today = db.scalar(select(func.date(func.now())))
    if local_today is None:
        local_today = datetime.now(timezone.utc).date()
    start_date = local_today - timedelta(days=days - 1)

    trend_rows = db.execute(
        _alarm_list_stmt(scope, project_id=project_id)
        .with_only_columns(
            func.date(Alarm.alarm_time).label("d"),
            Alarm.alarm_level,
            func.count().label("c"),
        )
        .where(func.date(Alarm.alarm_time) >= literal(start_date))
        .group_by(func.date(Alarm.alarm_time), Alarm.alarm_level)
    ).all()

    # 预填整窗（含零值日期），保证「无告警日」仍出现在趋势中
    buckets: dict[str, dict[str, int]] = {}
    for i in range(days):
        ds = (start_date + timedelta(days=i)).isoformat()
        buckets[ds] = {"date": ds, "total": 0, "严重": 0, "警告": 0, "提示": 0}
    for d, lvl, c in trend_rows:
        # d 在 PG 为 date、在 SQLite 为 'YYYY-MM-DD' 字符串，统一取前 10 位
        ds = (d.isoformat() if isinstance(d, date) else str(d))[:10]
        b = buckets.get(ds)
        if b is None:
            continue
        b["total"] += c
        if lvl in _ALARM_LEVEL_ORDER:
            b[lvl] += c
    trend = list(buckets.values())

    # —— KPI ——
    pending = count_alarms(db, scope, project_id=project_id, handle_status="待处理")
    pending_critical = (
        db.scalar(
            select(func.count()).select_from(
                _alarm_list_stmt(scope, project_id=project_id, handle_status="待处理")
                .where(Alarm.alarm_level == "严重")
                .subquery()
            )
        )
        or 0
    )
    active_preventive = count_alarms(
        db, scope, project_id=project_id, alarm_type=ALARM_TYPE_PREVENTIVE, handle_status="待处理"
    )
    today_new = (
        db.scalar(
            select(func.count()).select_from(
                _alarm_list_stmt(scope, project_id=project_id)
                .where(func.date(Alarm.alarm_time) == func.date(func.now()))
                .subquery()
            )
        )
        or 0
    )

    # 待处理按级别分布
    pl_rows = db.execute(
        _alarm_list_stmt(scope, project_id=project_id, handle_status="待处理")
        .with_only_columns(Alarm.alarm_level, func.count())
        .group_by(Alarm.alarm_level)
    ).all()
    pending_by_level = {lvl: c for lvl, c in pl_rows}

    return {
        "kpi": {
            "today_new": today_new,
            "pending": pending,
            "pending_critical": pending_critical,
            "active_preventive": active_preventive,
        },
        "pending_by_level": pending_by_level,
        "trend": trend,
    }


def count_alarms(
    db: Session,
    scope: DataScope,
    project_id: int | None = None,
    alarm_type: str | None = None,
    handle_status: str | None = None,
    alarm_status: str | None = None,
    device_no: str | None = None,
) -> int:
    """在同一过滤 + 部门隔离下返回告警**真实总数**（供分页 total）。"""
    stmt = _alarm_list_stmt(
        scope,
        project_id=project_id,
        alarm_type=alarm_type,
        handle_status=handle_status,
        alarm_status=alarm_status,
        device_no=device_no,
    )
    return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


def list_alarms(
    db: Session,
    scope: DataScope,
    project_id: int | None = None,
    alarm_type: str | None = None,
    handle_status: str | None = None,
    alarm_status: str | None = None,
    device_no: str | None = None,
    page: int = 1,
    size: int = 20,
) -> list[dict]:
    """按 page/size 真分页返回告警列表（offset 分页），施加部门数据隔离。"""
    page = max(1, page)
    size = max(1, size)
    stmt = _alarm_list_stmt(
        scope,
        project_id=project_id,
        alarm_type=alarm_type,
        handle_status=handle_status,
        alarm_status=alarm_status,
        device_no=device_no,
    )
    stmt = (
        stmt.order_by(Alarm.alarm_time.desc().nullslast(), Alarm.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    rows = db.scalars(stmt).all()
    return [to_alarm_out(a) for a in rows]


def handle_alarm(
    db: Session,
    alarm_id: int,
    handle_status: str,
    content: str | None = None,
) -> dict[str, Any] | None:
    """处置告警（处理/忽略/已确认/已消警）。返回序列化结果或 None。

    若置为「已消警」，调用方应据返回的设备信息下发消警指令（见 app.mqtt）。
    """
    alarm = db.get(Alarm, alarm_id)
    if alarm is None:
        return None
    alarm.handle_status = handle_status
    if content is not None:
        alarm.handle_content = content
    if handle_status == ALARM_STATUS_CLEARED:
        alarm.alarm_status = ALARM_STATUS_CLEARED
    db.flush()
    return to_alarm_out(alarm)


def update_alarm_media(db: Session, alarm_id: int, urls: list[str]) -> list[str] | None:
    """整体替换某告警的媒体 URL 列表（去重后存为 JSON 字符串）。

    返回更新后的解析列表；告警不存在返回 None。
    """
    alarm = db.get(Alarm, alarm_id)
    if alarm is None:
        return None
    seen: list[str] = []
    for u in urls or []:
        if u and u not in seen:
            seen.append(u)
    alarm.media_urls = json.dumps(seen, ensure_ascii=False) if seen else None
    # 不在 service 内提交：事务统一由调用端点提交（#7 约定 service 不提交）
    db.flush()
    return _parse_media(alarm.media_urls)


def count_open(db: Session, scope: DataScope) -> int:
    """统计待处理告警数（大屏角标用）。"""
    stmt = select(func.count()).select_from(Alarm)
    stmt = apply_data_scope(stmt, Alarm, scope)
    stmt = stmt.where(Alarm.handle_status == "待处理")
    return db.scalar(stmt) or 0


# ---------------------------------------------------------------------------
# 告警报表 / 导出
# ---------------------------------------------------------------------------

#: 告警类型英文枚举 → 中文展示名（报表/导出使用）
ALARM_TYPE_LABELS: dict[str, str] = {
    "fence_intrusion": "围栏侵入",
    "distance_too_close": "间距过近",
    "device_alarm": "设备自报",
    "train_approach": "列车接近预警",
    "trend_anomaly": "趋势异常",
    "predictive_alert": "预测预警",
    "preventive_alert": "预防式预警",
}


def alarm_type_label(t: str | None) -> str:
    return ALARM_TYPE_LABELS.get(t or "", t or "未知")


def query_alarms_for_report(
    db: Session,
    scope: DataScope,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    project_id: int | None = None,
    alarm_type: str | None = None,
    handle_status: str | None = None,
    alarm_level: str | None = None,
    limit: int | None = 5000,
) -> list[dict]:
    """报表明细查询：支持时间范围 + 多维过滤 + 部门数据隔离。

    与 list_alarms 的区别：新增 start/end/alarm_level 过滤，limit 更大（导出用）。
    limit=None 表示不截断（历史快照整窗查询用，避免跨周期汇总被 5000 截断）。
    """
    stmt = select(Alarm)
    stmt = apply_data_scope(stmt, Alarm, scope)
    if start is not None:
        stmt = stmt.where(Alarm.alarm_time >= start)
    if end is not None:
        stmt = stmt.where(Alarm.alarm_time <= end)
    if project_id is not None:
        stmt = stmt.where(Alarm.project_id == project_id)
    if alarm_type is not None:
        stmt = stmt.where(Alarm.alarm_type == alarm_type)
    if handle_status is not None:
        stmt = stmt.where(Alarm.handle_status == handle_status)
    if alarm_level is not None:
        stmt = stmt.where(Alarm.alarm_level == alarm_level)
    stmt = stmt.order_by(Alarm.alarm_time.desc().nullslast(), Alarm.id.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = db.scalars(stmt).all()
    return [to_alarm_out(a) for a in rows]


def _period_key(at: str | None, granularity: str) -> str:
    """把告警时间字符串映射为聚合周期 key。

    - day:   YYYY-MM-DD（当天）
    - week:  YYYY-Www（ISO 周，周一为首日）
    - month: YYYY-MM（当月）
    """
    if not isinstance(at, str) or len(at) < 7:
        return "未知"
    if granularity == "week":
        date_part = at[:19] if "T" in at else at[:10]
        try:
            d = datetime.fromisoformat(date_part)
        except ValueError:
            return "未知"
        iso = d.isocalendar()  # (iso_year, iso_week, iso_weekday)
        return f"{iso[0]}-W{iso[1]:02d}"
    if granularity == "month":
        return at[:7]
    return at[:10]


def aggregate_alarms(rows: list[dict], granularity: str = "day") -> dict[str, Any]:
    """对报表明细做聚合统计：总数 + 按类型/级别/处置状态/周期 分布。

    by_day 始终为「按天」分布（向后兼容报表弹窗旧行为）；
    by_period 按 granularity（day/week/month）分布，供趋势图按粒度切换。
    每项扩展为 {period, count, by_type, by_level}，供堆叠柱状图使用。
    """
    from collections import Counter

    by_type: Counter = Counter()
    by_level: Counter = Counter()
    by_handle: Counter = Counter()
    by_day: Counter = Counter()
    by_day_type: dict[str, Counter] = {}
    by_day_level: dict[str, Counter] = {}
    by_period: Counter = Counter()
    by_period_type: dict[str, Counter] = {}
    by_period_level: dict[str, Counter] = {}
    handled = 0
    for r in rows:
        t = r.get("alarm_type")
        lv = r.get("alarm_level") or "未分级"
        hs = r.get("handle_status") or "待处理"
        by_type[t] += 1
        by_level[lv] += 1
        by_handle[hs] += 1
        if hs not in ("待处理",):
            handled += 1
        at = r.get("alarm_time")
        day = at[:10] if isinstance(at, str) and len(at) >= 10 else "未知"
        by_day[day] += 1
        by_day_type.setdefault(day, Counter())[t] += 1
        by_day_level.setdefault(day, Counter())[lv] += 1
        period = _period_key(at, granularity)
        by_period[period] += 1
        by_period_type.setdefault(period, Counter())[t] += 1
        by_period_level.setdefault(period, Counter())[lv] += 1

    total = len(rows)
    by_day_out = []
    for day in sorted(by_day.keys()):
        by_day_out.append(
            {
                "date": day,
                "count": by_day[day],
                "by_type": {k: v for k, v in by_day_type[day].items()},
                "by_level": {k: v for k, v in by_day_level[day].items()},
            }
        )
    by_period_out = []
    for p in sorted(by_period.keys()):
        by_period_out.append(
            {
                "period": p,
                "count": by_period[p],
                "by_type": {k: v for k, v in by_period_type[p].items()},
                "by_level": {k: v for k, v in by_period_level[p].items()},
            }
        )
    return {
        "total": total,
        "handled": handled,
        "pending": total - handled,
        "handle_rate": round(handled / total, 4) if total else 0.0,
        "by_type": [
            {"key": k, "label": alarm_type_label(k), "count": v} for k, v in by_type.most_common()
        ],
        "by_level": [{"key": k, "count": v} for k, v in by_level.most_common()],
        "by_handle_status": [{"key": k, "count": v} for k, v in by_handle.most_common()],
        "by_day": by_day_out,
        "by_period": by_period_out,
    }


def aggregate_alarms_sql(
    db: Session,
    scope: DataScope,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    granularity: str = "day",
) -> dict[str, Any]:
    """SQL 聚合下推版：替代 ``query_alarms_for_report(limit=50000) + aggregate_alarms``

    的内存聚合，避免一次把多达数万条完整告警对象拉进 Python 再纯内存统计。

    仅对窗口内告警做 ``GROUP BY`` 聚合计数，返回结构与 :func:`aggregate_alarms`
    一致（dashboard 使用 ``by_period`` / ``by_level`` / ``by_handle_status``）。
    period key 在 Python 端用与 :func:`_period_key` 完全相同的算法生成，保证趋势图
    与计数卡联动自洽。截断前显式 ``timezone('UTC', alarm_time)``，规避会话时区漂移。
    """
    from collections import Counter

    gran = (granularity or "day").lower()
    if gran not in ("day", "week", "month"):
        gran = "day"

    # 注意：必须与旧逻辑 ``to_alarm_out`` 的 ``alarm_time.isoformat()`` 日期切片完全一致。
    # alarm_time 是 timestamptz，SQLAlchemy 按 PG session 时区（当前 Asia/Shanghai）返回
    # aware 值，旧逻辑 ``_period_key(at)`` 取的是「session 时区显示的日期」。因此这里用
    # ``date_trunc`` 的默认（session 时区）截断，而非 timezone('UTC', ...)——后者会按 UTC
    # 日界，与已上线的趋势图/计数卡联动语义错位（跨午夜告警会漂移）。
    bucket_ts = func.date_trunc(gran, Alarm.alarm_time)
    stmt = select(
        bucket_ts.label("bucket"),
        Alarm.alarm_type,
        Alarm.alarm_level,
        Alarm.handle_status,
        func.count().label("cnt"),
    )
    if start is not None:
        stmt = stmt.where(Alarm.alarm_time >= start)
    if end is not None:
        stmt = stmt.where(Alarm.alarm_time <= end)
    stmt = apply_data_scope(stmt, Alarm, scope)
    stmt = stmt.group_by(bucket_ts, Alarm.alarm_type, Alarm.alarm_level, Alarm.handle_status)
    raw = db.execute(stmt).all()

    by_period: dict[str, dict] = {}
    by_type: Counter = Counter()
    by_level: Counter = Counter()
    by_handle: Counter = Counter()
    for bucket, atype, alevel, ahandle, cnt in raw:
        if bucket is None:
            continue
        period = _period_key(bucket.isoformat(), gran)
        pe = by_period.setdefault(period, {"count": 0, "by_type": Counter(), "by_level": Counter()})
        pe["count"] += cnt
        pe["by_type"][atype] += cnt
        pe["by_level"][(alevel or "未分级")] += cnt
        by_type[atype] += cnt
        by_level[(alevel or "未分级")] += cnt
        by_handle[(ahandle or "待处理")] += cnt

    by_period_out = [
        {
            "period": p,
            "count": v["count"],
            "by_type": dict(v["by_type"]),
            "by_level": dict(v["by_level"]),
        }
        for p, v in sorted(by_period.items())
    ]
    total = sum(v["count"] for v in by_period.values())
    return {
        "total": total,
        "by_type": [
            {"key": k, "label": alarm_type_label(k), "count": v} for k, v in by_type.most_common()
        ],
        "by_level": [{"key": k, "count": v} for k, v in by_level.most_common()],
        "by_handle_status": [{"key": k, "count": v} for k, v in by_handle.most_common()],
        "by_period": by_period_out,
        "by_day": [],
    }

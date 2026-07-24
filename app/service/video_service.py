"""视频通道/AI 事件服务层（P3·⑧ PoC）。

- 通道台账 CRUD（数据隔离 VIA_PROJECT，channel_no 全局唯一）。
- 事件回推：按 channel_no 找通道→留痕→（ai_enabled 才接受）。
- 事件按通道可见性过滤（通道可见即事件可见）。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now_local
from app.core.data_scope import DataScope, apply_data_scope
from app.core.exceptions import BusinessError
from app.model.project import Project
from app.model.video import VideoChannel, VideoEvent
from app.schema.video import (
    VIDEO_EVENT_TYPE_LABELS,
    VIDEO_EVENT_TYPES,
    VideoChannelOut,
    VideoEventOut,
)


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
    return e


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

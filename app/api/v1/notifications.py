"""通知中心路由：列表 / 未读计数 / 标记已读 / 全部已读。

通知自解释：所有查询均按当前登录用户过滤（user_id = 当前用户），无需部门数据隔离。
鉴权仅要求登录（get_current_user）。
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_permissions
from app.core.gateways import send_via_gateway
from app.core.responses import ApiResponse
from app.model.notification import Notification
from app.model.notification_delivery import NotificationDelivery
from app.model.system import User
from app.schema.notification import NotificationDeliveryOut, NotificationOut, NotificationPage

router = APIRouter(tags=["通知中心"])


def _base_stmt(user: User):
    return select(Notification).where(Notification.user_id == user.id)


@router.get(
    "",
    summary="我的通知列表",
    response_model=ApiResponse,
)
def list_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    unread_only: bool = Query(False, description="仅看未读"),
    page: int = 1,
    size: int = 20,
) -> ApiResponse:
    """分页返回当前用户的通知；支持仅看未读。"""
    page = max(1, page)
    size = max(1, size)
    stmt = _base_stmt(user)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    unread = (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        )
        or 0
    )
    rows = db.scalars(
        stmt.order_by(Notification.created_at.desc().nullslast(), Notification.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return ApiResponse.success(
        data=NotificationPage(
            total=total,
            unread=unread,
            items=[NotificationOut.model_validate(n) for n in rows],
            page=page,
            size=size,
        ).model_dump()
    )


@router.get(
    "/unread-count",
    summary="未读数量",
    response_model=ApiResponse,
)
def unread_count(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApiResponse:
    cnt = (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        )
        or 0
    )
    return ApiResponse.success(data={"count": cnt})


@router.post(
    "/{notification_id}/read",
    summary="标记单条已读",
    response_model=ApiResponse,
)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApiResponse:
    n = db.scalar(_base_stmt(user).where(Notification.id == notification_id))
    if n is None:
        return ApiResponse.fail("通知不存在", code=404)
    n.is_read = True
    db.flush()
    db.commit()
    return ApiResponse.success(data={"id": notification_id, "is_read": True})


@router.post(
    "/read-all",
    summary="全部标记已读",
    response_model=ApiResponse,
)
def mark_all_read(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApiResponse:
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.is_read.is_(False))
        .update({Notification.is_read: True}, synchronize_session=False)
    )
    db.commit()
    return ApiResponse.success(data={"updated": updated})


class TestSendReq(BaseModel):
    channel: str  # sms | voice
    phone: str
    content: str = "测试通知：涉铁监控模拟网关触达校验"


@router.get(
    "/deliveries",
    summary="短信/语音网关触达记录（模拟真实数据）",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("dashboard:view"))],
)
def list_deliveries(
    db: Session = Depends(get_db),
    channel: str | None = Query(None, description="sms/voice 过滤"),
    limit: int = Query(50, ge=1, le=200),
) -> ApiResponse:
    """分页返回短信/语音网关触达回执（模拟模式下即「模拟真实数据」的发送记录）。"""
    stmt = select(NotificationDelivery)
    if channel:
        stmt = stmt.where(NotificationDelivery.channel == channel)
    rows = db.scalars(stmt.order_by(NotificationDelivery.id.desc()).limit(limit)).all()
    return ApiResponse.success(
        data=[NotificationDeliveryOut.model_validate(r).model_dump() for r in rows]
    )


@router.post(
    "/test-send",
    summary="模拟网关下发（验证链路/触达）",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("dashboard:view"))],
)
def test_send(
    body: TestSendReq,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApiResponse:
    """经网关下发一条测试短信/语音（默认模拟模式），返回网关回执与落库记录。

    用于在无第三方凭据阶段验证「平台 → 网关 → 触达记录」全链路，并核对真实形态回执。
    """
    if body.channel not in ("sms", "voice"):
        return ApiResponse.fail("channel 仅支持 sms/voice", code=400)
    result = send_via_gateway(body.channel, body.phone, body.content)
    rec = NotificationDelivery(**result.to_record(user_id=user.id))
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return ApiResponse.success(
        data={
            "result": asdict(result),
            "delivery": NotificationDeliveryOut.model_validate(rec).model_dump(),
        }
    )

"""通知中心路由：列表 / 未读计数 / 标记已读 / 全部已读。

通知自解释：所有查询均按当前登录用户过滤（user_id = 当前用户），无需部门数据隔离。
鉴权仅要求登录（get_current_user）。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.responses import ApiResponse
from app.model.notification import Notification
from app.model.system import User
from app.schema.notification import NotificationOut, NotificationPage

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

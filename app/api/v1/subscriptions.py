"""定期订阅推送路由（模块①·报告与触达增强）。

- ``GET  /subscriptions``：列出当前用户的订阅（超管可 ``?all=true`` 看全部）。
- ``POST /subscriptions``：创建订阅（归属当前用户）。
- ``PUT  /subscriptions/{id}``：更新（仅归属用户/超管）。
- ``DEL  /subscriptions/{id}``：删除。
- ``POST /subscriptions/{id}/trigger``：手动立即触发一次生成+触达（绕过到期判定）。
- ``GET  /subscriptions/{id}/download``：按订阅参数即时重生报告并下载（尊重当前用户数据范围）。

权限：``dashboard:view``（与报告同源）。订阅按归属隔离，非归属且非超管返回 404（不泄露存在性）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.data_scope import DataScope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.exceptions import BusinessError
from app.core.responses import ApiResponse
from app.model.report_subscription import ReportSubscription as _Sub
from app.model.system import User
from app.service import report_subscription as svc
from app.service.effectiveness_export import (
    disposition_header,
    generate_effectiveness_report,
)

router = APIRouter(prefix="/v1/subscriptions", tags=["报告订阅"])


class SubscriptionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    fmt: str = Field("excel", pattern="^(excel|pdf)$")
    days: int = Field(30, ge=7, le=365)
    project_id: int | None = Field(None, ge=1)
    frequency: str = Field("daily", pattern="^(daily|weekly|monthly)$")
    send_hour: int = Field(8, ge=0, le=23)
    send_weekday: int = Field(0, ge=0, le=6)
    send_day: int = Field(1, ge=1, le=28)
    channels: list[str] = Field(default_factory=lambda: ["in_app"])
    enabled: bool = True


class SubscriptionUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    fmt: str | None = Field(None, pattern="^(excel|pdf)$")
    days: int | None = Field(None, ge=7, le=365)
    project_id: int | None = Field(None, ge=1)
    frequency: str | None = Field(None, pattern="^(daily|weekly|monthly)$")
    send_hour: int | None = Field(None, ge=0, le=23)
    send_weekday: int | None = Field(None, ge=0, le=6)
    send_day: int | None = Field(None, ge=1, le=28)
    channels: list[str] | None = None
    enabled: bool | None = None


@router.get("")
def list_subscriptions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(require_permissions("dashboard:view")),
    all_flag: bool = Query(False, description="超管查看全部订阅"),
) -> ApiResponse:
    stmt = _base_stmt()
    if not (all_flag and current_user.is_superuser):
        stmt = stmt.where(_Sub.user_id == current_user.id)
    rows = db.scalars(stmt).all()
    return ApiResponse.success(data=[r.to_dict() for r in rows])


@router.post("")
def create_subscription(
    req: SubscriptionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(require_permissions("dashboard:view")),
) -> ApiResponse:
    payload: dict[str, Any] = req.model_dump()
    sub = svc.create_subscription(db, current_user, payload)
    return ApiResponse.success(data=sub.to_dict(), message="订阅已创建")


@router.put("/{sub_id}")
def update_subscription(
    sub_id: int,
    req: SubscriptionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(require_permissions("dashboard:view")),
) -> ApiResponse:
    sub = svc.get_owned_or_404(db, sub_id, current_user, allow_super=True)
    if sub is None:
        raise BusinessError("订阅不存在或无权访问", code=404)
    payload = {k: v for k, v in req.model_dump(exclude_unset=True).items()}
    sub = svc.update_subscription(db, sub, payload)
    return ApiResponse.success(data=sub.to_dict(), message="订阅已更新")


@router.delete("/{sub_id}")
def delete_subscription(
    sub_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(require_permissions("dashboard:view")),
) -> ApiResponse:
    sub = svc.get_owned_or_404(db, sub_id, current_user, allow_super=True)
    if sub is None:
        raise BusinessError("订阅不存在或无权访问", code=404)
    svc.delete_subscription(db, sub)
    return ApiResponse.success(message="订阅已删除")


@router.post("/{sub_id}/trigger")
def trigger_subscription(
    sub_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(require_permissions("dashboard:view")),
) -> ApiResponse:
    sub = svc.get_owned_or_404(db, sub_id, current_user, allow_super=True)
    if sub is None:
        raise BusinessError("订阅不存在或无权访问", code=404)
    try:
        summary = svc.run_one(db, sub, datetime.now(timezone.utc))
        db.commit()
        return ApiResponse.success(data=summary, message="已立即生成并触达")
    except Exception as e:  # noqa: BLE001
        db.rollback()
        sub.last_run_at = datetime.now(timezone.utc)
        sub.last_status = "failed"
        sub.last_error = str(e)[:500]
        db.commit()
        raise BusinessError(f"触发失败：{str(e)[:200]}", code=500)


@router.get("/{sub_id}/download")
def download_subscription(
    sub_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: DataScope = Depends(get_data_scope),
    _: User = Depends(require_permissions("dashboard:view")),
) -> StreamingResponse:
    sub = svc.get_owned_or_404(db, sub_id, current_user, allow_super=True)
    if sub is None:
        raise BusinessError("订阅不存在或无权访问", code=404)
    # 按当前用户数据范围即时重生（尊重点击者自身权限，不越权）
    content, filename, media_type = generate_effectiveness_report(
        db, scope, days=sub.days, fmt=sub.fmt, project_id=sub.project_id
    )
    ascii_name = f"subscription_{sub.id}.{'pdf' if sub.fmt == 'pdf' else 'xlsx'}"
    disposition = disposition_header(filename, ascii_name)
    return StreamingResponse(
        iter([content]), media_type=media_type, headers={"Content-Disposition": disposition}
    )


def _base_stmt():
    from sqlalchemy import select

    return select(_Sub).order_by(_Sub.id.desc())

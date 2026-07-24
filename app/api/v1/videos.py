"""视频通道 / AI 事件路由（P3·⑧ PoC）。

- GET    /channels           通道列表（video:list）
- POST   /channels           登记通道（video:create）
- PUT    /channels/{id}      更新通道（video:update）
- DELETE /channels/{id}      软删通道（video:delete）
- POST   /events/ingest      外部推理服务回推事件（video:ingest，服务账号 JWT）
- GET    /events             事件列表（video:list）
- POST   /events/{id}/handle 标记已处理（video:update）

重推理不在平台落地：外部服务持服务账号 JWT 调 /events/ingest 回推结构化事件。
"""

from fastapi import APIRouter, Depends

from app.core.data_scope import DataScope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.responses import ApiResponse
from app.model.system import User
from app.schema.video import (
    VideoChannelCreate,
    VideoChannelUpdate,
    VideoEventIngest,
)
from app.service import video_service as svc

router = APIRouter(tags=["视频AI"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "videos", "status": "ready"}


@router.get(
    "/channels",
    summary="视频通道列表",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("video:list"))],
)
def list_channels(
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = None,
    keyword: str | None = None,
    page: int = 1,
    size: int = 20,
) -> ApiResponse:
    total, rows = svc.list_channels(
        db, scope, project_id=project_id, keyword=keyword, page=page, size=size
    )
    return ApiResponse.success(
        data={
            "total": total,
            "items": [svc.to_channel_out(db, c).model_dump() for c in rows],
            "page": page,
            "size": size,
        }
    )


@router.post(
    "/channels",
    summary="登记视频通道",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("video:create"))],
)
def create_channel(
    payload: VideoChannelCreate,
    db=Depends(get_db),
    current: User = Depends(get_current_user),
) -> ApiResponse:
    c = svc.create_channel(db, payload.model_dump(), current.id)
    db.commit()
    return ApiResponse.success(data=svc.to_channel_out(db, c).model_dump())


@router.put(
    "/channels/{channel_id}",
    summary="更新视频通道",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("video:update"))],
)
def update_channel(
    channel_id: int,
    payload: VideoChannelUpdate,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    c = svc.update_channel(db, channel_id, payload.model_dump(exclude_unset=True), scope)
    if c is None:
        return ApiResponse.fail(message="通道不存在或无权访问", code=404)
    db.commit()
    return ApiResponse.success(data=svc.to_channel_out(db, c).model_dump())


@router.delete(
    "/channels/{channel_id}",
    summary="删除视频通道",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("video:delete"))],
)
def delete_channel(
    channel_id: int, db=Depends(get_db), scope: DataScope = Depends(get_data_scope)
) -> ApiResponse:
    ok = svc.delete_channel(db, channel_id, scope)
    if not ok:
        return ApiResponse.fail(message="通道不存在或无权访问", code=404)
    db.commit()
    return ApiResponse.success(message="删除成功")


@router.post(
    "/events/ingest",
    summary="AI 事件回推（外部推理服务）",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("video:ingest"))],
)
def ingest_event(payload: VideoEventIngest, db=Depends(get_db)) -> ApiResponse:
    """外部推理服务/AI 盒子回推结构化事件；持服务账号 JWT 调用。

    通道级安全（数据范围）不适用于机器回推——按 channel_no 全局定位，
    但仅 ai_enabled 的未删通道接受事件。
    """
    e = svc.ingest_event(db, payload.model_dump())
    db.commit()
    return ApiResponse.success(data=svc.to_event_out(e).model_dump(), message="事件已接收")


@router.get(
    "/events",
    summary="AI 事件列表",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("video:list"))],
)
def list_events(
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    channel_id: int | None = None,
    project_id: int | None = None,
    event_type: str | None = None,
    handled: bool | None = None,
    page: int = 1,
    size: int = 20,
) -> ApiResponse:
    total, rows = svc.list_events(
        db,
        scope,
        channel_id=channel_id,
        project_id=project_id,
        event_type=event_type,
        handled=handled,
        page=page,
        size=size,
    )
    return ApiResponse.success(
        data={
            "total": total,
            "items": [svc.to_event_out(e).model_dump() for e in rows],
            "page": page,
            "size": size,
        }
    )


@router.post(
    "/events/{event_id}/handle",
    summary="标记事件已处理",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("video:update"))],
)
def handle_event(
    event_id: int, db=Depends(get_db), scope: DataScope = Depends(get_data_scope)
) -> ApiResponse:
    e = svc.handle_event(db, event_id, scope)
    db.commit()
    return ApiResponse.success(data=svc.to_event_out(e).model_dump(), message="已处理")

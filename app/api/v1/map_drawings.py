"""地图手动绘制路由：标注点/线 CRUD（复用 map:* 权限）。

- GET    /options          可选枚举（类型/模式，map:list）
- GET    /                 标注列表（分页/模糊/类型/模式/项目过滤，map:list）
- POST   /                 创建标注（map:add）
- GET    /{drawing_id}     标注详情（map:list）
- PUT    /{drawing_id}     更新标注（map:edit）
- DELETE /{drawing_id}     删除标注（软删，map:delete）

地图标注为全局配置，不施加部门数据隔离。
"""

from fastapi import APIRouter, Depends, Query

from app.core.constants import (
    MAP_DRAWING_KIND_LABELS,
    MAP_DRAWING_KIND_MODES,
    MAP_DRAWING_KINDS,
    MAP_DRAWING_MODE_LABELS,
    MAP_DRAWING_MODES,
)
from app.core.data_scope import DataScope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.responses import ApiResponse
from app.model.map_drawing import MapDrawing
from app.model.system import User
from app.schema.common import IdList
from app.schema.map_drawing import MapDrawingCreate, MapDrawingOut, MapDrawingUpdate
from app.service import map_drawing_service as svc
from app.service.batch_ops import batch_soft_delete

router = APIRouter(tags=["地图维护"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "map-drawings", "status": "ready"}


@router.get(
    "/options",
    summary="地图标注可选枚举",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("map:list"))],
)
def list_options() -> ApiResponse:
    return ApiResponse.success(
        data={
            "kinds": [{"value": k, "label": MAP_DRAWING_KIND_LABELS[k]} for k in MAP_DRAWING_KINDS],
            "modes": [{"value": m, "label": MAP_DRAWING_MODE_LABELS[m]} for m in MAP_DRAWING_MODES],
            "kind_modes": {k: list(v) for k, v in MAP_DRAWING_KIND_MODES.items()},
        }
    )


@router.get(
    "",
    summary="地图标注列表",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("map:list"))],
)
def list_drawings(
    db=Depends(get_db),
    keyword: str | None = Query(None, description="按名称/备注/标注人模糊搜索"),
    kind: str | None = Query(None, description="按标注类型过滤: point/line"),
    mode: str | None = Query(None, description="按绘制模式过滤: free/coord/road"),
    project_id: int | None = Query(None, description="按项目过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> ApiResponse:
    total, rows = svc.list_drawings(
        db, keyword=keyword, kind=kind, mode=mode, project_id=project_id, page=page, size=size
    )
    items = [MapDrawingOut.model_validate(r).model_dump() for r in rows]
    return ApiResponse.success(data={"total": total, "items": items, "page": page, "size": size})


@router.post(
    "",
    summary="创建地图标注",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("map:add"))],
)
def create_drawing(
    payload: MapDrawingCreate,
    db=Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApiResponse:
    data = payload.model_dump()
    if not data.get("operator"):
        data["operator"] = getattr(user, "username", None)
    row = svc.create_drawing(db, data)
    db.commit()
    return ApiResponse.success(data=MapDrawingOut.model_validate(row).model_dump())


@router.get(
    "/{drawing_id}",
    summary="地图标注详情",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("map:list"))],
)
def get_drawing(drawing_id: int, db=Depends(get_db)) -> ApiResponse:
    row = svc.get_drawing(db, drawing_id)
    if row is None:
        return ApiResponse.fail(message=f"地图标注不存在：{drawing_id}", code=404)
    return ApiResponse.success(data=MapDrawingOut.model_validate(row).model_dump())


@router.put(
    "/{drawing_id}",
    summary="更新地图标注",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("map:edit"))],
)
def update_drawing(drawing_id: int, payload: MapDrawingUpdate, db=Depends(get_db)) -> ApiResponse:
    row = svc.update_drawing(db, drawing_id, payload.model_dump(exclude_unset=True))
    db.commit()
    return ApiResponse.success(data=MapDrawingOut.model_validate(row).model_dump())


@router.delete(
    "/{drawing_id}",
    summary="删除地图标注",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("map:delete"))],
)
def delete_drawing(drawing_id: int, db=Depends(get_db)) -> ApiResponse:
    svc.delete_drawing(db, drawing_id)
    db.commit()
    return ApiResponse.success(message="删除成功")


@router.post(
    "/batch-delete",
    response_model=ApiResponse,
    summary="批量删除地图标注（软删）",
    dependencies=[Depends(require_permissions("map:delete"))],
)
def batch_delete(
    items: IdList,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """批量软删地图标注（全局配置，不做数据隔离，与单选一致）。"""
    deleted = batch_soft_delete(MapDrawing, db, scope, items.ids)
    total = len(items.ids)
    db.commit()
    return ApiResponse.success(
        data={"deleted": deleted, "total": total, "skipped": total - deleted},
        message=f"已删除 {deleted} 条",
    )

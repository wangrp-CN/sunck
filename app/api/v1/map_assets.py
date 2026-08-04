"""地图资源库路由：CRUD 与列表（按 map:* 权限管控）。

- GET    /              资源列表（分页/模糊/类型过滤，map:list）
- POST   /              创建资源（map:add）
- GET    /{asset_id}   资源详情（map:list）
- PUT    /{asset_id}   更新资源（map:edit）
- DELETE /{asset_id}   删除资源（软删，map:delete）

地图资源为全局配置，不施加部门数据隔离。
"""

from fastapi import APIRouter, Depends, Query

from app.core.data_scope import DataScope
from app.core.database import get_db
from app.core.deps import get_data_scope, require_permissions
from app.core.responses import ApiResponse
from app.model.map_asset import MapAsset
from app.schema.common import IdList
from app.schema.map_asset import MapAssetCreate, MapAssetOut, MapAssetUpdate
from app.service import map_asset_service as svc
from app.service.batch_ops import batch_soft_delete

router = APIRouter(tags=["地图维护"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "maps", "status": "ready"}


@router.get(
    "",
    summary="地图资源列表",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("map:list"))],
)
def list_assets(
    db=Depends(get_db),
    keyword: str | None = Query(None, description="按名称/备注/维护人模糊搜索"),
    asset_type: str | None = Query(None, description="按资源类型过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> ApiResponse:
    total, rows = svc.list_assets(db, keyword=keyword, asset_type=asset_type, page=page, size=size)
    items = [MapAssetOut.model_validate(r).model_dump() for r in rows]
    return ApiResponse.success(data={"total": total, "items": items, "page": page, "size": size})


@router.post(
    "",
    summary="创建地图资源",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("map:add"))],
)
def create_asset(payload: MapAssetCreate, db=Depends(get_db)) -> ApiResponse:
    asset = svc.create_asset(db, payload.model_dump())
    db.commit()
    return ApiResponse.success(data=MapAssetOut.model_validate(asset).model_dump())


@router.get(
    "/{asset_id}",
    summary="地图资源详情",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("map:list"))],
)
def get_asset(asset_id: int, db=Depends(get_db)) -> ApiResponse:
    asset = svc.get_asset(db, asset_id)
    if asset is None:
        return ApiResponse.fail(message=f"地图资源不存在：{asset_id}", code=404)
    return ApiResponse.success(data=MapAssetOut.model_validate(asset).model_dump())


@router.put(
    "/{asset_id}",
    summary="更新地图资源",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("map:edit"))],
)
def update_asset(asset_id: int, payload: MapAssetUpdate, db=Depends(get_db)) -> ApiResponse:
    asset = svc.update_asset(db, asset_id, payload.model_dump(exclude_unset=True))
    db.commit()
    return ApiResponse.success(data=MapAssetOut.model_validate(asset).model_dump())


@router.delete(
    "/{asset_id}",
    summary="删除地图资源",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("map:delete"))],
)
def delete_asset(asset_id: int, db=Depends(get_db)) -> ApiResponse:
    svc.delete_asset(db, asset_id)
    db.commit()
    return ApiResponse.success(message="删除成功")


@router.post(
    "/batch-delete",
    response_model=ApiResponse,
    summary="批量删除地图资源（软删）",
    dependencies=[Depends(require_permissions("map:delete"))],
)
def batch_delete(
    items: IdList,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """批量软删地图资源（全局配置，不做数据隔离，与单选一致）。"""
    deleted = batch_soft_delete(MapAsset, db, scope, items.ids)
    total = len(items.ids)
    db.commit()
    return ApiResponse.success(
        data={"deleted": deleted, "total": total, "skipped": total - deleted},
        message=f"已删除 {deleted} 条",
    )

"""数据字典路由：字典类型/字典项 CRUD 与下拉引用，按 dict:* 权限管控。

- GET    /                    字典类型列表（含项，分页，dict:list）
- POST   /                    创建字典类型（可带初始项，dict:create）
- GET    /{code}              类型详情（dict:list）
- PUT    /{code}              更新类型名称/说明（dict:update）
- DELETE /{code}              删除类型（系统内置不可删，dict:delete）
- GET    /{code}/items        字典项列表（enabled_only 供下拉，dict:list）
- POST   /{code}/items        新增字典项（dict:update）
- PUT    /items/{item_id}     更新字典项（dict:update）
- DELETE /items/{item_id}     删除字典项（系统内置不可删，dict:update）

字典为全局配置，不施加部门数据隔离。
"""

from fastapi import APIRouter, Depends, Query

from app.core.database import get_db
from app.core.deps import require_permissions
from app.core.responses import ApiResponse
from app.schema.dict import (
    DictItemCreate,
    DictItemOut,
    DictItemUpdate,
    DictTypeCreate,
    DictTypeOut,
    DictTypeUpdate,
)
from app.service import dict_service as svc

router = APIRouter(tags=["数据字典"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "dicts", "status": "ready"}


@router.get(
    "",
    summary="字典类型列表",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("dict:list"))],
)
def list_types(
    db=Depends(get_db),
    keyword: str | None = Query(None, description="按编码/名称/说明模糊搜索"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> ApiResponse:
    total, rows = svc.list_types(db, keyword=keyword, page=page, size=size)
    items = [DictTypeOut.model_validate(r).model_dump() for r in rows]
    return ApiResponse.success(data={"total": total, "items": items, "page": page, "size": size})


@router.post(
    "",
    summary="创建字典类型",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("dict:create"))],
)
def create_type(payload: DictTypeCreate, db=Depends(get_db)) -> ApiResponse:
    data = payload.model_dump()
    data["items"] = [i for i in data.get("items", [])]
    dt = svc.create_type(db, data)
    db.commit()
    return ApiResponse.success(data=DictTypeOut.model_validate(dt).model_dump())


@router.get(
    "/{code}",
    summary="字典类型详情",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("dict:list"))],
)
def get_type(code: str, db=Depends(get_db)) -> ApiResponse:
    dt = svc.get_type(db, code)
    if dt is None:
        return ApiResponse.fail(message=f"字典类型不存在：{code}", code=404)
    return ApiResponse.success(data=DictTypeOut.model_validate(dt).model_dump())


@router.put(
    "/{code}",
    summary="更新字典类型",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("dict:update"))],
)
def update_type(code: str, payload: DictTypeUpdate, db=Depends(get_db)) -> ApiResponse:
    dt = svc.update_type(db, code, payload.model_dump(exclude_unset=True))
    db.commit()
    return ApiResponse.success(data=DictTypeOut.model_validate(dt).model_dump())


@router.delete(
    "/{code}",
    summary="删除字典类型",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("dict:delete"))],
)
def delete_type(code: str, db=Depends(get_db)) -> ApiResponse:
    svc.delete_type(db, code)
    db.commit()
    return ApiResponse.success(message="删除成功")


@router.get(
    "/{code}/items",
    summary="字典项列表",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("dict:list"))],
)
def list_items(
    code: str,
    db=Depends(get_db),
    enabled_only: bool = Query(False, description="仅启用项(供前端下拉引用)"),
) -> ApiResponse:
    rows = svc.list_items(db, code, enabled_only=enabled_only)
    return ApiResponse.success(data=[DictItemOut.model_validate(r).model_dump() for r in rows])


@router.post(
    "/{code}/items",
    summary="新增字典项",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("dict:update"))],
)
def create_item(code: str, payload: DictItemCreate, db=Depends(get_db)) -> ApiResponse:
    item = svc.create_item(db, code, payload.model_dump())
    db.commit()
    return ApiResponse.success(data=DictItemOut.model_validate(item).model_dump())


@router.put(
    "/items/{item_id}",
    summary="更新字典项",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("dict:update"))],
)
def update_item(item_id: int, payload: DictItemUpdate, db=Depends(get_db)) -> ApiResponse:
    item = svc.update_item(db, item_id, payload.model_dump(exclude_unset=True))
    db.commit()
    return ApiResponse.success(data=DictItemOut.model_validate(item).model_dump())


@router.delete(
    "/items/{item_id}",
    summary="删除字典项",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("dict:update"))],
)
def delete_item(item_id: int, db=Depends(get_db)) -> ApiResponse:
    svc.delete_item(db, item_id)
    db.commit()
    return ApiResponse.success(message="删除成功")

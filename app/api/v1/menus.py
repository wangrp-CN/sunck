"""菜单管理路由：基于 Permission 模型的菜单树管理。

支持的菜单类型：
- type=1：目录（导航分组）
- type=2：菜单项（页面路由）
- type=3：按钮/接口权限

本路由提供完整的菜单树管理能力（含按钮权限）。
导航渲染请使用 `/tree` 端点，它仅返回已启用的目录与菜单。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_permissions
from app.core.responses import ApiResponse
from app.model.system import User
from app.schema.common import IdList
from app.schema.menu import MenuCreate, MenuUpdate
from app.service import menu_service

router = APIRouter(tags=["菜单管理"])


# ── 查询 ──────────────────────────────────────────────────


@router.get("", summary="菜单树列表", response_model=ApiResponse)
def list_menus(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("menu:list")),
    keyword: str | None = Query(None, description="按名称/标识/路径/组件搜索"),
    type: int | None = Query(None, ge=1, le=3, description="类型: 1=目录 2=菜单 3=按钮"),
    status: bool | None = Query(None, description="启用状态"),
) -> ApiResponse:
    tree = menu_service.list_menus_tree(
        db,
        keyword=keyword,
        type_filter=type,
        status=status,
    )
    return ApiResponse.success(data=[t.model_dump() for t in tree])


@router.get("/tree", summary="菜单树（供角色权限分配/导航渲染）", response_model=ApiResponse)
def menu_tree(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("menu:list")),
) -> ApiResponse:
    tree = menu_service.get_menu_tree(db)
    return ApiResponse.success(data=[t.model_dump() for t in tree])


@router.get("/options", summary="上级菜单下拉选项", response_model=ApiResponse)
def menu_options(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("menu:list")),
) -> ApiResponse:
    options = menu_service.get_menu_options(db)
    return ApiResponse.success(data=[o.model_dump() for o in options])


@router.get("/{menu_id}", summary="菜单详情", response_model=ApiResponse)
def get_menu(
    menu_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("menu:list")),
) -> ApiResponse:
    menu = menu_service.get_menu(db, menu_id)
    if menu is None:
        return ApiResponse.fail(message="菜单不存在")
    return ApiResponse.success(data=menu_service._model_to_out(menu).model_dump())


# ── 写入 ──────────────────────────────────────────────────


@router.post("", summary="新建菜单", response_model=ApiResponse, status_code=201)
def create_menu(
    data: MenuCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("menu:add")),
) -> ApiResponse:
    menu = menu_service.create_menu(db, data)
    db.commit()
    return ApiResponse.success(
        data=menu_service._model_to_out(menu).model_dump(),
        message="菜单创建成功",
    )


@router.put("/{menu_id}", summary="更新菜单", response_model=ApiResponse)
def update_menu(
    menu_id: int,
    data: MenuUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("menu:edit")),
) -> ApiResponse:
    menu = menu_service.get_menu(db, menu_id)
    if menu is None:
        return ApiResponse.fail(message="菜单不存在")
    menu = menu_service.update_menu(db, menu, data)
    db.commit()
    return ApiResponse.success(
        data=menu_service._model_to_out(menu).model_dump(),
        message="菜单更新成功",
    )


@router.delete("/{menu_id}", summary="删除菜单（含子菜单）", response_model=ApiResponse)
def delete_menu(
    menu_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("menu:delete")),
) -> ApiResponse:
    menu = menu_service.get_menu(db, menu_id)
    if menu is None:
        return ApiResponse.fail(message="菜单不存在")
    menu_service.delete_menu(db, menu)
    db.commit()
    return ApiResponse.success(message="菜单及子菜单已删除")


# ── 批量 ──────────────────────────────────────────────────


@router.post("/batch-delete", summary="批量删除菜单", response_model=ApiResponse)
def batch_delete_menus(
    body: IdList,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("menu:delete")),
) -> ApiResponse:
    result = menu_service.batch_delete_menus(db, body.ids)
    db.commit()
    return ApiResponse.success(data=result)

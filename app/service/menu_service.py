"""菜单服务层：基于 Permission 模型的菜单树管理。

菜单是 Permission 表的子集：
- type=1：目录（导航分组）
- type=2：菜单项（页面路由）
- type=3：按钮/接口权限（也可在菜单管理中维护）
"""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.model.system import Permission
from app.schema.menu import MenuCreate, MenuOut, MenuTreeOut, MenuUpdate


def _model_to_out(m: Permission) -> MenuOut:
    return MenuOut.model_validate(m)


def _build_tree(menus: list[Permission], parent_id: int | None = None) -> list[MenuTreeOut]:
    """递归构建菜单树。"""
    children = [m for m in menus if m.parent_id == parent_id]
    result: list[MenuTreeOut] = []
    for m in sorted(children, key=lambda x: (x.sort, x.id)):
        node = MenuTreeOut.model_validate(m)
        node.children = _build_tree(menus, m.id)
        result.append(node)
    return result


def _filter_tree_keep_ancestors(menus: list[Permission], keep_ids: set[int]) -> list[Permission]:
    """保留命中节点及其所有祖先节点（用于关键词过滤后的树展示）。"""
    menu_by_id = {m.id: m for m in menus}
    ids_to_keep: set[int] = set()

    for menu_id in keep_ids:
        current = menu_id
        while current is not None:
            ids_to_keep.add(current)
            current = menu_by_id.get(current)
            if current is None:
                break
            current = current.parent_id

    return [m for m in menus if m.id in ids_to_keep]


# ── 列表 / 树 ──────────────────────────────────────────────


def list_menus_tree(
    db: Session,
    *,
    keyword: str | None = None,
    type_filter: int | None = None,
    status: bool | None = None,
) -> list[MenuTreeOut]:
    """获取完整菜单树（含目录、菜单、按钮）。

    关键词过滤时会保留命中节点的祖先链，确保树结构完整。
    """
    stmt = select(Permission).where(
        Permission.is_deleted.is_(False),
    )
    if type_filter is not None:
        stmt = stmt.where(Permission.type == type_filter)
    if status is not None:
        stmt = stmt.where(Permission.status == status)

    menus = list(db.scalars(stmt.order_by(Permission.sort.asc(), Permission.id.asc())).all())

    if keyword:
        like = f"%{keyword}%"
        matched = {
            m.id
            for m in menus
            if (m.name and like in m.name)
            or (m.code and like in m.code)
            or (m.path and like in m.path)
            or (m.component and like in m.component)
        }
        menus = _filter_tree_keep_ancestors(menus, matched)

    return _build_tree(menus)


def get_menu_tree(db: Session) -> list[MenuTreeOut]:
    """获取完整菜单树（只含已启用的目录和菜单，供导航渲染）。"""
    menus = db.scalars(
        select(Permission)
        .where(
            Permission.is_deleted.is_(False),
            Permission.status.is_(True),
            Permission.type.in_([1, 2]),
        )
        .order_by(Permission.sort.asc(), Permission.id.asc())
    ).all()
    return _build_tree(list(menus))


def get_menu_options(db: Session) -> list[MenuOut]:
    """获取上级菜单下拉选项（所有未删除的目录/菜单，不含按钮）。"""
    menus = db.scalars(
        select(Permission)
        .where(
            Permission.is_deleted.is_(False),
            Permission.type.in_([1, 2]),
        )
        .order_by(Permission.sort.asc(), Permission.id.asc())
    ).all()
    return [_model_to_out(m) for m in menus]


# ── 单条 CRUD ─────────────────────────────────────────────


def get_menu(db: Session, menu_id: int) -> Permission | None:
    return db.scalar(
        select(Permission).where(Permission.id == menu_id, Permission.is_deleted.is_(False))
    )


def create_menu(db: Session, data: MenuCreate) -> Permission:
    menu = Permission(**data.model_dump())
    db.add(menu)
    db.flush()
    return menu


def update_menu(db: Session, menu: Permission, data: MenuUpdate) -> Permission:
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(menu, key, value)
    db.flush()
    return menu


def delete_menu(db: Session, menu: Permission) -> None:
    """软删菜单及所有子菜单。"""
    all_ids = _collect_descendant_ids(db, menu.id)
    all_ids.add(menu.id)
    db.execute(update(Permission).where(Permission.id.in_(all_ids)).values(is_deleted=True))


def _collect_descendant_ids(db: Session, parent_id: int) -> set[int]:
    """递归查找某节点下的所有子孙节点 ID。"""
    ids: set[int] = set()
    children = db.scalars(
        select(Permission.id).where(
            Permission.parent_id == parent_id,
            Permission.is_deleted.is_(False),
        )
    ).all()
    for child_id in children:
        ids.add(child_id)
        ids.update(_collect_descendant_ids(db, child_id))
    return ids


# ── 批量删除 ──────────────────────────────────────────────


def batch_delete_menus(db: Session, ids: list[int]) -> dict:
    """批量软删菜单（含子树），返回 {deleted, total, skipped}。"""
    total = len(ids)
    deleted = 0
    skipped = 0
    for menu_id in ids:
        menu = get_menu(db, menu_id)
        if menu is None:
            skipped += 1
            continue
        delete_menu(db, menu)
        deleted += 1
    return {"deleted": deleted, "total": total, "skipped": skipped}

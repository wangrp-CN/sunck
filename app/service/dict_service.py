"""数据字典服务层：字典类型/字典项 CRUD 与系统内置只读保护。

- system=True 的字典类型不可删除、不可改 code，其字典项允许追加/启停但不可删除
  （保障平台核心枚举稳定，前端可继续下拉引用）。
- 字典为全局配置，不施加部门数据隔离；按 dict:* 权限管控。
- 端点统一提交（service 不 commit）。
"""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.model.dict import DictItem, DictType


def _get_type_or_raise(db: Session, code: str) -> DictType:
    dt = db.scalar(select(DictType).where(DictType.code == code))
    if dt is None:
        raise BusinessError(f"字典类型不存在：{code}", code=404)
    return dt


def list_types(
    db: Session,
    keyword: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[int, list[DictType]]:
    """分页列出字典类型（含字典项，selectin 预载）。"""
    stmt = select(DictType)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                DictType.code.ilike(like),
                DictType.name.ilike(like),
                DictType.description.ilike(like),
            )
        )
    stmt = stmt.order_by(DictType.id.desc())
    rows = list(db.scalars(stmt).all())
    total = len(rows)
    start = max(0, (page - 1) * size)
    return total, rows[start : start + size]


def get_type(db: Session, code: str) -> DictType | None:
    return db.scalar(select(DictType).where(DictType.code == code))


def create_type(db: Session, data: dict) -> DictType:
    """创建字典类型（可携带初始字典项）。code 重复报业务错误。"""
    code = (data.get("code") or "").strip()
    if not code:
        raise BusinessError("字典类型编码不能为空", code=400)
    if db.scalar(select(DictType).where(DictType.code == code)):
        raise BusinessError(f"字典类型编码已存在：{code}", code=400)
    items = data.pop("items", []) or []
    dt = DictType(code=code, name=data.get("name") or code, description=data.get("description"))
    db.add(dt)
    db.flush()
    for i in items:
        db.add(DictItem(type_code=code, **i))
    db.flush()
    db.refresh(dt)
    return dt


def update_type(db: Session, code: str, data: dict) -> DictType:
    """更新字典类型名称/说明（code 不可改；系统内置同样允许改名/说明）。"""
    dt = _get_type_or_raise(db, code)
    for k in ("name", "description"):
        v = data.get(k)
        if v is not None:
            setattr(dt, k, v)
    db.flush()
    return dt


def delete_type(db: Session, code: str) -> None:
    """删除字典类型（级联删字典项）；系统内置不可删。"""
    dt = _get_type_or_raise(db, code)
    if dt.system:
        raise BusinessError("系统内置字典类型不可删除", code=400)
    db.delete(dt)
    db.flush()


def list_items(db: Session, code: str, enabled_only: bool = False) -> list[DictItem]:
    """列出某类型下的字典项（sort 升序）；enabled_only 供前端下拉引用。"""
    _get_type_or_raise(db, code)
    stmt = select(DictItem).where(DictItem.type_code == code)
    if enabled_only:
        stmt = stmt.where(DictItem.enabled.is_(True))
    stmt = stmt.order_by(DictItem.sort.asc(), DictItem.id.asc())
    return list(db.scalars(stmt).all())


def create_item(db: Session, code: str, data: dict) -> DictItem:
    """新增字典项；同类型下 value 不可重复。"""
    _get_type_or_raise(db, code)
    value = (data.get("value") or "").strip()
    if not value:
        raise BusinessError("字典项存储值不能为空", code=400)
    dup = db.scalar(select(DictItem).where(DictItem.type_code == code, DictItem.value == value))
    if dup:
        raise BusinessError(f"字典项已存在：{value}", code=400)
    item = DictItem(type_code=code, **data)
    db.add(item)
    db.flush()
    return item


def update_item(db: Session, item_id: int, data: dict) -> DictItem:
    """更新字典项（label/value/sort/enabled/remark/ext）。"""
    item = db.get(DictItem, item_id)
    if item is None:
        raise BusinessError("字典项不存在", code=404)
    new_value = data.get("value")
    if new_value is not None and new_value != item.value:
        dup = db.scalar(
            select(DictItem).where(
                DictItem.type_code == item.type_code,
                DictItem.value == new_value,
                DictItem.id != item_id,
            )
        )
        if dup:
            raise BusinessError(f"字典项已存在：{new_value}", code=400)
    for k in ("label", "value", "sort", "enabled", "remark", "ext"):
        v = data.get(k)
        if v is not None:
            setattr(item, k, v)
    db.flush()
    return item


def delete_item(db: Session, item_id: int) -> None:
    """删除字典项；系统内置类型下的字典项不可删（可停用）。"""
    item = db.get(DictItem, item_id)
    if item is None:
        raise BusinessError("字典项不存在", code=404)
    if item.type is not None and item.type.system:
        raise BusinessError("系统内置字典项不可删除（可停用）", code=400)
    db.delete(item)
    db.flush()

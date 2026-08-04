"""批量操作辅助：通用软删 / 硬删，供各实体批量删除端点复用。

设计原则：与对应实体的「单选删除」保持语义完全一致。

- 软删（默认）：仅对「数据范围内 + 尚未删除」的记录置 ``is_deleted=True``；
  已注册数据隔离（``_MODEL_DEPT_LINK``）的模型会施加 ``apply_data_scope``，
  未注册的模型（地图资源/标注）跳过隔离，与单选端点行为对齐。
- 硬删：直接 ``DELETE``，用于未携带 ``is_deleted`` 列的模型（字典项），
  同样不做数据隔离，与单选删除端点一致。

返回被实际删除的记录数，便于端点上报 ``deleted/total/skipped``。
"""

from typing import Iterable

from sqlalchemy import delete as sa_delete
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.data_scope import _MODEL_DEPT_LINK, DataScope
from app.schema.common import IdList


def batch_soft_delete(
    model,
    db: Session,
    scope: DataScope,
    ids: Iterable[int],
    *,
    id_col: str = "id",
    deleted_col: str = "is_deleted",
) -> int:
    """通用软删：返回实际删除（置位）的记录数。

    - 仅在 ``id_col in ids`` 且 ``deleted_col is False`` 的记录中操作；
    - 模型已注册数据隔离时叠加 ``apply_data_scope``，否则跳过（与单选对齐）；
    - 超管（scope.is_all）对所有可见记录生效。
    """
    pk = getattr(model, id_col)
    dc = getattr(model, deleted_col)
    stmt = select(pk).where(pk.in_(ids), dc.is_(False))
    if model in _MODEL_DEPT_LINK:
        from app.core.data_scope import apply_data_scope

        stmt = apply_data_scope(stmt, model, scope)
    visible = db.scalars(stmt).all()
    if visible:
        db.execute(update(model).where(pk.in_(visible)).values({deleted_col: True}))
    return len(visible)


def batch_hard_delete(
    model,
    db: Session,
    ids: Iterable[int],
    *,
    id_col: str = "id",
) -> int:
    """通用硬删：直接物理删除 ``id_col in ids`` 的记录，返回删除行数。

    仅用于无 ``is_deleted`` 列的模型（如字典项）；不做数据隔离，与单选端点一致。
    """
    pk = getattr(model, id_col)
    res = db.execute(sa_delete(model).where(pk.in_(ids)))
    return int(res.rowcount or 0)


__all__ = ["IdList", "batch_soft_delete", "batch_hard_delete"]

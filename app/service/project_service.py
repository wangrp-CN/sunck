"""项目管理服务：工期计算与列表查询过滤构建。

约定（SOP）：服务层不提交事务，由端点负责 commit；本模块均为纯函数 / 只读查询辅助。
"""

from datetime import date

from sqlalchemy import false as sa_false
from sqlalchemy.orm import Session

from app.core.data_scope import get_department_descendant_ids
from app.model.project import Project


def calc_duration(start_date: date | None, end_date: date | None) -> int | None:
    """根据开工 / 完工日期计算工期（天）。

    - 两个日期均非空 → (end_date - start_date).days（可为负，由调用方决定如何处理）。
    - 任一为空 → 返回 None（工期未知）。
    """
    if start_date is None or end_date is None:
        return None
    return (end_date - start_date).days


def apply_project_list_filters(
    stmt,
    *,
    dept_ids: set[int] | None = None,
    name: str | None = None,
    start_date_from: date | None = None,
    start_date_to: date | None = None,
    end_date_from: date | None = None,
    end_date_to: date | None = None,
    status: str | None = None,
):
    """在既有项目查询语句上叠加列表过滤条件（AND 叠加）。

    数据范围过滤（apply_data_scope）由端点在调用本函数之后另行施加，二者互不干扰。

    - name：项目名称左右模糊（ilike %name%）。
    - dept_ids：归属部门集合（调用方应已展开含下级）；为空集合表示部门不存在 → 永假。
    - start_date_from/to、end_date_from/to：开工 / 完工日期区间（闭区间）。
    - status：精确匹配项目状态。
    """
    if name:
        stmt = stmt.where(Project.name.ilike(f"%{name}%"))
    if dept_ids is not None:
        if dept_ids:
            stmt = stmt.where(Project.dept_id.in_(dept_ids))
        else:
            # 指定了部门但展开后为空（部门不存在）：返回永假，确保查不到数据
            stmt = stmt.where(sa_false())
    if start_date_from is not None:
        stmt = stmt.where(Project.start_date >= start_date_from)
    if start_date_to is not None:
        stmt = stmt.where(Project.start_date <= start_date_to)
    if end_date_from is not None:
        stmt = stmt.where(Project.end_date >= end_date_from)
    if end_date_to is not None:
        stmt = stmt.where(Project.end_date <= end_date_to)
    if status:
        stmt = stmt.where(Project.status == status)
    return stmt


def expand_dept_ids(db: Session, dept_id: int | None) -> set[int] | None:
    """若传入 dept_id，返回该部门及其全部下级部门 ID 集合；否则返回 None（不限制）。"""
    if dept_id is None:
        return None
    return get_department_descendant_ids(db, dept_id)


__all__ = [
    "calc_duration",
    "apply_project_list_filters",
    "expand_dept_ids",
]

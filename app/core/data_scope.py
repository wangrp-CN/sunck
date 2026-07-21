"""部门数据隔离：数据范围解析与应用。

将当前用户多个角色的 data_scope 合并为统一的 :class:`DataScope`，供业务查询过滤：

- 1 全部数据：不做任何过滤（超级管理员强制为全部）。
- 2 自定义部门：角色经 role_dept 关联的部门，且自动包含其下级部门。
- 3 本部门及以下：用户所属部门及其全部下级部门。
- 4 仅本人：记录 created_by == 当前用户。

多角色取「并集」：任一角色为全部 → 整体为全部；本部门与自定义部门取部门并集；
仅本人作为额外 OR 条件叠加。

应用方式：在业务查询中调用 :func:`apply_data_scope` ，由注册表决定模型与部门的
关联方式（直接携带 dept_id，或经 project 关联）。
"""

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import false as sa_false
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.model.alarm import Alarm
from app.model.device import AntiIntrusionDevice, LocateDevice, TrainApproachDevice
from app.model.fence import ElectronicFence
from app.model.job import WorkPlan
from app.model.person import Machine, Person
from app.model.project import Project
from app.model.system import Department, User, role_dept

# ---------------------------------------------------------------------------
# 数据范围结果
# ---------------------------------------------------------------------------


@dataclass
class DataScope:
    """解析后的数据范围。

    - is_all：true 时表示可访问全部数据，无需过滤。
    - dept_ids：允许访问的部门 ID 集合（已展开含下级）。
    - include_self：是否额外包含「本人创建」的记录。
    - self_user_id：本人用户 ID（配合 include_self 使用）。
    """

    is_all: bool = False
    dept_ids: set[int] = field(default_factory=set)
    include_self: bool = False
    self_user_id: Optional[int] = None

    def has_filter(self) -> bool:
        """是否需要在查询上施加过滤条件。"""
        return not self.is_all


# ---------------------------------------------------------------------------
# 部门层级工具
# ---------------------------------------------------------------------------


def get_department_descendant_ids(db: Session, root_id: int) -> set[int]:
    """返回 root 部门及其所有后代部门 ID（含自身），基于 parent_id 逐层展开。"""
    result: set[int] = set()
    current: set[int] = {root_id}
    while current:
        result |= current
        rows = db.scalars(
            select(Department.id).where(
                Department.parent_id.in_(current), Department.is_deleted.is_(False)
            )
        ).all()
        current = set(rows)
    return result


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------


def resolve_data_scope(user: User, db: Session) -> DataScope:
    """根据用户角色列表合并出统一的数据范围。

    - 超级管理员直接返回全部。
    - 任一角色 data_scope==1 也视为全部。
    - 其余角色按 2/3/4 累加部门集合或标记仅本人。
    """
    if user.is_superuser:
        return DataScope(is_all=True)

    scope = DataScope()
    for role in user.roles:
        if role.data_scope == 1:
            return DataScope(is_all=True)
        if role.data_scope == 2:
            # 自定义部门：取角色关联部门，并展开其下级
            dept_rows = db.scalars(
                select(role_dept.c.dept_id).where(role_dept.c.role_id == role.id)
            ).all()
            for dept_id in dept_rows:
                scope.dept_ids.update(get_department_descendant_ids(db, dept_id))
        elif role.data_scope == 3:
            # 本部门及以下
            if user.dept_id is not None:
                scope.dept_ids.update(get_department_descendant_ids(db, user.dept_id))
        elif role.data_scope == 4:
            # 仅本人
            scope.include_self = True
            scope.self_user_id = user.id

    return scope


# ---------------------------------------------------------------------------
# 模型 -> 部门 关联注册表
# ---------------------------------------------------------------------------

#: 模型直接携带 dept_id 列（与 department 表直连）。
DIRECT = "direct"
#: 模型经 project 关联，部门判定落在 project.dept_id 上。
VIA_PROJECT = "via_project"


_MODEL_DEPT_LINK: dict[type, str] = {
    User: DIRECT,
    Project: DIRECT,
    LocateDevice: VIA_PROJECT,
    AntiIntrusionDevice: VIA_PROJECT,
    TrainApproachDevice: VIA_PROJECT,
    Person: VIA_PROJECT,
    Machine: VIA_PROJECT,
    ElectronicFence: VIA_PROJECT,
    WorkPlan: VIA_PROJECT,
    Alarm: VIA_PROJECT,
}


# ---------------------------------------------------------------------------
# 实体 → 归属项目 解析（供媒体等按 key 归口的端点复用）
# ---------------------------------------------------------------------------

#: 实体类型 → ORM 模型（用于解析其归属项目 ID）。
_ENTITY_PROJECT_MODEL: dict[str, type] = {
    "project": Project,
    "work_plan": WorkPlan,
    "alarm": Alarm,
    "device": LocateDevice,
    "person": Person,
    "machine": Machine,
}


def resolve_entity_project_id(db: Session, entity_type: str, entity_id: int) -> Optional[int]:
    """根据关联实体类型与 ID 解析其归属项目 ID；无法解析返回 None。

    - ``project`` 自身即项目，直接返回 entity_id。
    - 其余类型（work_plan/alarm/device/person/machine）取其 project_id。
    - 模型未注册或记录不存在返回 None。
    """
    if entity_type == "project":
        return entity_id
    model = _ENTITY_PROJECT_MODEL.get(entity_type)
    if model is None:
        return None
    obj = db.get(model, entity_id)
    if obj is None:
        return None
    return getattr(obj, "project_id", None)


# ---------------------------------------------------------------------------
# 应用过滤
# ---------------------------------------------------------------------------


def apply_data_scope(stmt, model: type, scope: DataScope):
    """在查询语句上施加数据范围过滤，返回新的语句。

    - is_all：原样返回。
    - 部门条件：DIRECT 用 model.dept_id.in_；VIA_PROJECT 用 model.project.has(Project.dept_id.in_)。
    - 仅本人条件（模型须有 created_by 列）：model.created_by == 当前用户。
    - 若合并后无任何可见条件（如仅本人但模型无创建人列），返回永假过滤（无权看任何数据）。
    """
    if scope.is_all:
        return stmt

    link = _MODEL_DEPT_LINK.get(model)
    conditions = []

    if scope.dept_ids and link is not None:
        if link == DIRECT:
            conditions.append(model.dept_id.in_(scope.dept_ids))
        else:  # VIA_PROJECT
            conditions.append(model.project.has(Project.dept_id.in_(scope.dept_ids)))

    if scope.include_self and scope.self_user_id is not None and hasattr(model, "created_by"):
        conditions.append(model.created_by == scope.self_user_id)

    if not conditions:
        # 没有任何可见条件：返回永假查询，确保不泄露数据
        return stmt.where(sa_false())

    return stmt.where(or_(*conditions))


__all__ = [
    "DataScope",
    "DIRECT",
    "VIA_PROJECT",
    "get_department_descendant_ids",
    "resolve_data_scope",
    "resolve_entity_project_id",
    "apply_data_scope",
]

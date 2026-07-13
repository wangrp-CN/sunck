"""系统管理域模型：部门、用户、角色、权限及关联表（RBAC 完整实现）。

对应需求 §2.10 系统管理（用户/角色/权限）与 §1.1 角色权限设计：
- 用户(User) ↔ 角色(Role)：多对多，经 user_role 关联表维护。
- 角色(Role) ↔ 权限(Permission)：多对多，经 role_permission 关联表维护。
- 部门(Department)、权限(Permission) 支持树形结构（parent_id 自关联）。
- 主表统一携带 is_deleted 软删除标记与创建/更新时间。

所有表通过 Base.metadata 注册，由 Alembic 生成迁移（见 alembic/env.py）。
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, TimestampMixin

# ---------------------------------------------------------------------------
# 关联表（多对多，无额外业务字段，使用核心 Table 便于声明 relationship）
# ---------------------------------------------------------------------------
user_role = Table(
    "user_role",
    Base.metadata,
    Column(
        "user_id",
        Integer,
        ForeignKey("user.id", ondelete="CASCADE"),
        primary_key=True,
        comment="用户ID",
    ),
    Column(
        "role_id",
        Integer,
        ForeignKey("role.id", ondelete="CASCADE"),
        primary_key=True,
        comment="角色ID",
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default=func.now(),
        comment="授权时间",
    ),
)

role_permission = Table(
    "role_permission",
    Base.metadata,
    Column(
        "role_id",
        Integer,
        ForeignKey("role.id", ondelete="CASCADE"),
        primary_key=True,
        comment="角色ID",
    ),
    Column(
        "permission_id",
        Integer,
        ForeignKey("permission.id", ondelete="CASCADE"),
        primary_key=True,
        comment="权限ID",
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default=func.now(),
        comment="授权时间",
    ),
)

role_dept = Table(
    "role_dept",
    Base.metadata,
    Column(
        "role_id",
        Integer,
        ForeignKey("role.id", ondelete="CASCADE"),
        primary_key=True,
        comment="角色ID",
    ),
    Column(
        "dept_id",
        Integer,
        ForeignKey("department.id", ondelete="CASCADE"),
        primary_key=True,
        comment="部门ID(自定义数据范围)",
    ),
)


class SoftDeleteMixin:
    """软删除混入：逻辑删除，避免物理删除导致关联数据悬空。"""

    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否软删除"
    )


class Department(Base, TimestampMixin, SoftDeleteMixin):
    """部门（支持树形结构）。"""

    __tablename__ = "department"

    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="部门名称")
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="部门编码")
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("department.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="上级部门ID",
    )
    leader: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="负责人")
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="联系电话")
    sort: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序")
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")


class User(Base, TimestampMixin, SoftDeleteMixin):
    """用户（登录账号）。密码以 bcrypt 哈希存储。"""

    __tablename__ = "user"

    username: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True, comment="登录账号"
    )
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="昵称")
    password_hash: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="密码哈希(bcrypt)"
    )
    email: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="邮箱")
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="手机号")
    gender: Mapped[str | None] = mapped_column(String(8), nullable=True, comment="性别")
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="头像地址")
    dept_id: Mapped[int | None] = mapped_column(
        ForeignKey("department.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="归属部门ID",
    )
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    is_superuser: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否超级管理员(绕过权限校验)"
    )
    # 登录失败重试限制
    login_fail_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="连续登录失败次数"
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="账户锁定截止时间"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最近登录时间"
    )
    last_login_ip: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="最近登录IP"
    )

    roles: Mapped[list["Role"]] = relationship(
        secondary=user_role,
        back_populates="users",
        lazy="selectin",
        viewonly=False,
    )

    @property
    def role_codes(self) -> list[str]:
        return [r.code for r in self.roles]

    @property
    def permission_codes(self) -> list[str]:
        codes: set[str] = set()
        for role in self.roles:
            for perm in role.permissions:
                codes.add(perm.code)
        return list(codes)


class Role(Base, TimestampMixin, SoftDeleteMixin):
    """角色（权限的集合载体）。"""

    __tablename__ = "role"

    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="角色名称")
    code: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True, comment="角色编码"
    )
    data_scope: Mapped[int] = mapped_column(
        Integer,
        default=4,
        nullable=False,
        comment="数据权限范围(1=全部 2=自定义部门(含下级) 3=本部门及以下 4=仅本人)",
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否系统内置(不可删除)"
    )
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")

    users: Mapped[list["User"]] = relationship(
        secondary=user_role, back_populates="roles", lazy="selectin", viewonly=False
    )
    permissions: Mapped[list["Permission"]] = relationship(
        secondary=role_permission, back_populates="roles", lazy="selectin", viewonly=False
    )


class Permission(Base, TimestampMixin, SoftDeleteMixin):
    """权限（菜单/按钮/接口），支持树形结构。

    code 为权限唯一标识（如 user:list），后端通过它做接口访问控制。
    type: 1=目录 2=菜单 3=按钮/接口。
    """

    __tablename__ = "permission"

    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="权限名称")
    code: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True, comment="权限标识"
    )
    type: Mapped[int] = mapped_column(
        Integer, default=3, nullable=False, comment="类型(1目录 2菜单 3按钮/接口)"
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("permission.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="上级权限ID",
    )
    path: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="前端路由")
    component: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="前端组件")
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="图标")
    sort: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序")
    status: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")

    roles: Mapped[list["Role"]] = relationship(
        secondary=role_permission,
        back_populates="permissions",
        lazy="selectin",
        viewonly=False,
    )


class DictData(Base, TimestampMixin):
    """数据字典（设备类型/人员类型/围栏类型等），骨架预留。"""

    __tablename__ = "dict_data"

    dict_type: Mapped[str] = mapped_column(String(64), comment="字典类型")
    dict_label: Mapped[str] = mapped_column(String(64), comment="显示名")
    dict_value: Mapped[str] = mapped_column(String(64), comment="存储值")
    sort: Mapped[int] = mapped_column(default=0, comment="排序")

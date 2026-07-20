"""认证与 RBAC 相关 Schema（请求/响应模型，含中文说明）。

对应需求 §2.2 登录认证与 §2.10 用户/角色/权限管理。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# 登录 / 令牌
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=64, description="登录账号")
    password: str = Field(..., min_length=6, max_length=128, description="登录密码")
    # 验证码（需求 §2.2.1 必填；由 GET /auth/captcha 获取，登录时校验）
    captcha: str | None = Field(None, description="图形验证码(由 /auth/captcha 获取)")
    captcha_key: str | None = Field(None, description="验证码key(由 /auth/captcha 返回)")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., description="刷新令牌")


class TokenResponse(BaseModel):
    access_token: str = Field(..., description="访问令牌")
    refresh_token: str = Field(..., description="刷新令牌")
    token_type: str = Field("bearer", description="令牌类型")


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=6, max_length=128, description="原密码")
    new_password: str = Field(..., min_length=6, max_length=128, description="新密码")


# ---------------------------------------------------------------------------
# 用户
# ---------------------------------------------------------------------------


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=64, description="登录账号")
    password: str = Field(..., min_length=6, max_length=128, description="初始密码")
    nickname: str | None = Field(None, description="昵称")
    email: str | None = Field(None, description="邮箱")
    phone: str | None = Field(None, description="手机号")
    dept_id: int | None = Field(None, description="归属部门ID")
    role_codes: list[str] = Field(default_factory=list, description="分配的角色编码列表")
    status: bool = Field(True, description="是否启用")


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str | None = None
    email: str | None = None
    phone: str | None = None
    dept_id: int | None = None
    status: bool
    is_superuser: bool
    roles: list[str] = []
    permissions: list[str] = []
    last_login_at: datetime | None = None
    created_at: datetime | None = None


class UserPage(BaseModel):
    items: list[UserOut]
    total: int
    page: int
    size: int


class UserProfileUpdate(BaseModel):
    """个人中心-资料修改（仅可改自身非敏感字段）。"""

    nickname: str | None = Field(None, max_length=64, description="昵称")
    avatar: str | None = Field(None, max_length=255, description="头像地址")
    email: str | None = Field(None, max_length=128, description="邮箱")
    phone: str | None = Field(None, max_length=32, description="手机号")


class UserUpdateRequest(BaseModel):
    """管理员编辑用户（含部门/状态/角色，密码留空则不改）。"""

    nickname: str | None = Field(None, max_length=64, description="昵称")
    email: str | None = Field(None, max_length=128, description="邮箱")
    phone: str | None = Field(None, max_length=32, description="手机号")
    dept_id: int | None = Field(None, description="归属部门ID")
    status: bool | None = Field(None, description="是否启用")
    role_codes: list[str] | None = Field(None, description="分配的角色编码列表")
    password: str | None = Field(None, min_length=6, max_length=128, description="留空则不修改密码")


# ---------------------------------------------------------------------------
# 角色
# ---------------------------------------------------------------------------


class RoleCreateRequest(BaseModel):
    name: str = Field(..., max_length=64, description="角色名称")
    code: str = Field(
        ..., max_length=64, pattern=r"^[a-zA-Z0-9_:]+$", description="角色编码(字母数字下划线冒号)"
    )
    data_scope: int = Field(
        4, description="数据权限范围(1全部 2自定义部门(含下级) 3本部门及以下 4仅本人)"
    )
    dept_ids: list[int] = Field(
        default_factory=list, description="自定义数据范围部门ID列表(仅 data_scope=2 时生效)"
    )
    remark: str | None = Field(None, description="备注")


class RoleUpdateRequest(BaseModel):
    name: str | None = Field(None, description="角色名称")
    data_scope: int | None = Field(None, description="数据权限范围")
    remark: str | None = Field(None, description="备注")
    status: bool | None = Field(None, description="是否启用")


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    data_scope: int
    is_system: bool
    remark: str | None = None
    status: bool
    permission_codes: list[str] = []
    dept_ids: list[int] = Field(default_factory=list, description="自定义数据范围部门ID")


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    type: int
    parent_id: int | None = None
    path: str | None = None
    icon: str | None = None
    sort: int
    status: bool


class RolePermissionAssign(BaseModel):
    permission_codes: list[str] = Field(..., description="要赋予该角色的权限标识列表")


class RoleDeptAssign(BaseModel):
    dept_ids: list[int] = Field(..., description="自定义数据范围部门ID列表(全量覆盖)")

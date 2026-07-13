"""认证与 RBAC 路由：登录、令牌刷新、当前用户、登出、改密、用户/角色/权限管理。

统一返回结构：ApiResponse[T]（code=0 成功，非 0 失败），异常由全局处理器兜底。
访问控制：
- 公开接口：/login、/refresh
- 登录后可见：/me、/logout、/change-password、/permissions
- 需权限：/register(user:add)、/users(user:list)、/roles 系列(role:*)
"""

import base64
import random
import secrets
import string
from datetime import datetime, timedelta, timezone

from captcha.image import ImageCaptcha
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.data_scope import DataScope, apply_data_scope
from app.core.database import get_db
from app.core.deps import (
    get_current_active_superuser,
    get_current_user,
    get_data_scope,
    require_permissions,
)
from app.core.exceptions import BusinessError
from app.core.redis import get_redis_client
from app.core.responses import ApiResponse
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.model.system import Department, Permission, Role, User, role_dept
from app.schema.auth import (
    ChangePasswordRequest,
    LoginRequest,
    PermissionOut,
    RefreshRequest,
    RoleCreateRequest,
    RoleDeptAssign,
    RoleOut,
    RolePermissionAssign,
    RoleUpdateRequest,
    TokenResponse,
    UserCreateRequest,
    UserOut,
    UserPage,
    UserProfileUpdate,
)

router = APIRouter(tags=["认证"])


def _user_out(u: User) -> UserOut:
    """将 ORM 用户转换为对外输出（权限/角色取编码列表）。"""
    return UserOut(
        id=u.id,
        username=u.username,
        nickname=u.nickname,
        email=u.email,
        phone=u.phone,
        dept_id=u.dept_id,
        status=u.status,
        is_superuser=u.is_superuser,
        roles=u.role_codes,
        permissions=u.permission_codes,
        last_login_at=u.last_login_at,
        created_at=u.created_at,
    )


def _role_out(r: Role, db=None) -> RoleOut:
    """将 ORM 角色转换为对外输出（权限取编码列表）。"""
    dept_ids = []
    if db is not None:
        dept_ids = list(
            db.scalars(select(role_dept.c.dept_id).where(role_dept.c.role_id == r.id)).all()
        )
    return RoleOut(
        id=r.id,
        name=r.name,
        code=r.code,
        data_scope=r.data_scope,
        is_system=r.is_system,
        remark=r.remark,
        status=r.status,
        permission_codes=[p.code for p in r.permissions],
        dept_ids=dept_ids,
    )


def _assign_role_depts(db: Session, role_id: int, dept_ids: list[int]) -> None:
    """全量覆盖式写入角色-部门关联（自定义数据范围）。"""
    db.execute(role_dept.delete().where(role_dept.c.role_id == role_id))
    for dept_id in dept_ids:
        db.execute(role_dept.insert().values(role_id=role_id, dept_id=dept_id))


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------


@router.get("/captcha", summary="获取登录验证码")
def get_captcha() -> ApiResponse:
    """生成图形验证码，返回 key 与 base64 图片；答案存入 Redis（TTL）。"""
    code = "".join(
        random.choices(string.ascii_uppercase + string.digits, k=settings.captcha_length)
    )
    buf = ImageCaptcha(width=120, height=40).generate(code, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    key = secrets.token_hex(16)
    get_redis_client().set(f"captcha:{key}", code, ex=settings.captcha_ttl_seconds)
    return ApiResponse.success(
        {
            "captcha_key": key,
            "captcha_image": f"data:image/png;base64,{b64}",
            "expire_seconds": settings.captcha_ttl_seconds,
        },
        message="获取成功",
    )


@router.post("/login", response_model=ApiResponse[TokenResponse], summary="用户登录")
def login(
    req: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ApiResponse:
    """校验账号密码，成功返回访问/刷新令牌；失败按规则累计次数并锁定账户。"""
    from app.config import settings

    now = datetime.now(timezone.utc)
    user = db.execute(
        select(User).where(User.username == req.username, User.is_deleted.is_(False))
    ).scalar_one_or_none()

    # 不暴露账号是否存在，统一提示
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    # 已锁定检查
    if user.locked_until and user.locked_until > now:
        remain = int((user.locked_until - now).total_seconds() // 60) + 1
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"账户已锁定，请 {remain} 分钟后再试",
        )

    # 验证码校验（防爆破；测试环境可关闭）
    if settings.captcha_enabled:
        if not req.captcha or not req.captcha_key:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请输入验证码")
        stored = get_redis_client().get(f"captcha:{req.captcha_key}")
        if not stored or stored.upper() != req.captcha.upper():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误")
        get_redis_client().delete(f"captcha:{req.captcha_key}")

    # 密码校验
    if not verify_password(req.password, user.password_hash):
        user.login_fail_count = (user.login_fail_count or 0) + 1
        if user.login_fail_count >= settings.max_login_attempts:
            user.locked_until = now + timedelta(minutes=settings.account_lock_minutes)
            user.login_fail_count = 0
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"登录失败次数过多，账户已锁定 {settings.account_lock_minutes} 分钟",
            )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    # 启用状态
    if not user.status:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账户已被禁用")

    # 登录成功：重置失败计数并刷新登录信息
    user.login_fail_count = 0
    user.locked_until = None
    user.last_login_at = now
    user.last_login_ip = request.client.host if request.client else None
    db.commit()

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)
    return ApiResponse.success(
        TokenResponse(access_token=access_token, refresh_token=refresh_token),
        message="登录成功",
    )


@router.post("/refresh", response_model=ApiResponse[TokenResponse], summary="刷新令牌")
def refresh(req: RefreshRequest, db: Session = Depends(get_db)) -> ApiResponse:
    """使用刷新令牌换取新的访问/刷新令牌对。"""
    try:
        payload = decode_token(req.refresh_token, expected_type="refresh")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="刷新令牌无效或已过期")

    user = db.get(User, int(payload["sub"]))
    if user is None or user.is_deleted or not user.status:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已被禁用")

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)
    return ApiResponse.success(
        TokenResponse(access_token=access_token, refresh_token=refresh_token),
        message="令牌已刷新",
    )


# ---------------------------------------------------------------------------
# 登录后可见
# ---------------------------------------------------------------------------


@router.get("/me", response_model=ApiResponse[UserOut], summary="获取当前用户信息")
def get_me(current: User = Depends(get_current_user)) -> ApiResponse:
    """返回当前登录用户的基本信息、角色与权限。"""
    return ApiResponse.success(_user_out(current), message="获取成功")


@router.post("/logout", response_model=ApiResponse[None], summary="退出登录")
def logout(current: User = Depends(get_current_user)) -> ApiResponse:
    """无状态退出：客户端丢弃令牌即可。此处仅作语义端点。"""
    return ApiResponse.success(message="退出成功")


@router.post("/change-password", response_model=ApiResponse[None], summary="修改密码")
def change_password(
    req: ChangePasswordRequest,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse:
    """校验原密码后更新为新的哈希密码。"""
    if not verify_password(req.old_password, current.password_hash):
        raise BusinessError("原密码错误", code=400)
    try:
        validate_password_strength(req.new_password)
    except ValueError as e:
        raise BusinessError(str(e), code=400)
    current.password_hash = hash_password(req.new_password)
    current.login_fail_count = 0
    current.locked_until = None
    db.commit()
    return ApiResponse.success(message="密码修改成功")


@router.patch(
    "/me",
    response_model=ApiResponse[UserOut],
    summary="更新个人资料",
)
def update_profile(
    req: UserProfileUpdate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse:
    """更新当前登录用户的昵称/头像/邮箱/手机号；做基本格式校验。"""
    import re

    if req.email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", req.email):
        raise BusinessError("邮箱格式不正确", code=400)
    if req.phone and not re.match(r"^1\d{10}$", req.phone):
        raise BusinessError("手机号格式不正确", code=400)
    for field in ("nickname", "avatar", "email", "phone"):
        value = getattr(req, field)
        if value is not None:
            setattr(current, field, value)
    db.commit()
    db.refresh(current)
    return ApiResponse.success(_user_out(current), message="资料更新成功")


@router.get(
    "/permissions",
    response_model=ApiResponse[list[PermissionOut]],
    summary="权限列表",
)
def list_permissions(
    _: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ApiResponse:
    """返回全部权限（前端用于菜单/按钮渲染）。"""
    perms = db.scalars(
        select(Permission).where(Permission.is_deleted.is_(False)).order_by(Permission.sort)
    ).all()
    return ApiResponse.success([PermissionOut.model_validate(p) for p in perms], message="获取成功")


# ---------------------------------------------------------------------------
# 用户管理（需 user:add / user:list）
# ---------------------------------------------------------------------------


@router.post(
    "/register",
    response_model=ApiResponse[UserOut],
    summary="新建用户",
    dependencies=[Depends(require_permissions("user:add"))],
)
def register(req: UserCreateRequest, db: Session = Depends(get_db)) -> ApiResponse:
    """由管理员创建用户并分配角色（密码以 bcrypt 存储）。"""
    exists = db.scalar(
        select(User.id).where(User.username == req.username, User.is_deleted.is_(False))
    )
    if exists:
        raise BusinessError("用户名已存在", code=409)

    try:
        validate_password_strength(req.password)
    except ValueError as e:
        raise BusinessError(str(e), code=400)

    if req.role_codes:
        roles = db.scalars(
            select(Role).where(Role.code.in_(req.role_codes), Role.is_deleted.is_(False))
        ).all()
        if len(roles) != len(set(req.role_codes)):
            raise BusinessError("存在无效的角色编码", code=400)
    else:
        roles = []

    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        nickname=req.nickname,
        email=req.email,
        phone=req.phone,
        dept_id=req.dept_id,
        status=req.status,
        roles=roles,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return ApiResponse.success(_user_out(user), message="用户创建成功")


@router.get(
    "/users",
    response_model=ApiResponse[UserPage],
    summary="用户列表",
    dependencies=[Depends(require_permissions("user:list"))],
)
def list_users(
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    keyword: str | None = None,
    page: int = 1,
    size: int = 20,
) -> ApiResponse:
    """分页查询用户（支持按账号/昵称模糊搜索），并施加部门数据隔离。"""
    stmt = select(User).where(User.is_deleted.is_(False))
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(or_(User.username.ilike(kw), User.nickname.ilike(kw)))
    # 部门数据隔离：仅返回当前用户数据范围内的用户
    stmt = apply_data_scope(stmt, User, scope)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(User.id.desc()).offset((page - 1) * size).limit(size)).all()
    return ApiResponse.success(
        UserPage(
            items=[_user_out(u) for u in rows],
            total=total or 0,
            page=page,
            size=size,
        ),
        message="查询成功",
    )


# ---------------------------------------------------------------------------
# 角色管理（需 role:*）
# ---------------------------------------------------------------------------


@router.get(
    "/roles",
    response_model=ApiResponse[list[RoleOut]],
    summary="角色列表",
    dependencies=[Depends(require_permissions("role:list"))],
)
def list_roles(db: Session = Depends(get_db)) -> ApiResponse:
    """返回全部角色及其权限编码。"""
    roles = db.scalars(select(Role).where(Role.is_deleted.is_(False))).all()
    return ApiResponse.success([_role_out(r, db) for r in roles], message="查询成功")


@router.post(
    "/roles",
    response_model=ApiResponse[RoleOut],
    summary="新建角色",
    dependencies=[Depends(require_permissions("role:add"))],
)
def create_role(req: RoleCreateRequest, db: Session = Depends(get_db)) -> ApiResponse:
    """创建新角色（默认非系统内置）。"""
    if db.scalar(select(Role.id).where(Role.code == req.code, Role.is_deleted.is_(False))):
        raise BusinessError("角色编码已存在", code=409)
    role = Role(
        name=req.name,
        code=req.code,
        data_scope=req.data_scope,
        remark=req.remark,
    )
    db.add(role)
    db.flush()
    # 自定义数据范围（data_scope=2）：写入 role_dept 关联
    if req.data_scope == 2 and req.dept_ids:
        _assign_role_depts(db, role.id, req.dept_ids)
    db.commit()
    db.refresh(role)
    return ApiResponse.success(_role_out(role, db), message="角色创建成功")


@router.put(
    "/roles/{role_id}",
    response_model=ApiResponse[RoleOut],
    summary="更新角色",
    dependencies=[Depends(require_permissions("role:edit"))],
)
def update_role(role_id: int, req: RoleUpdateRequest, db: Session = Depends(get_db)) -> ApiResponse:
    role = db.get(Role, role_id)
    if role is None or role.is_deleted:
        raise BusinessError("角色不存在", code=404)
    if req.name is not None:
        role.name = req.name
    if req.data_scope is not None:
        role.data_scope = req.data_scope
    if req.remark is not None:
        role.remark = req.remark
    if req.status is not None:
        role.status = req.status
    db.commit()
    db.refresh(role)
    return ApiResponse.success(_role_out(role, db), message="角色更新成功")


@router.delete(
    "/roles/{role_id}",
    response_model=ApiResponse[None],
    summary="删除角色",
    dependencies=[Depends(require_permissions("role:delete"))],
)
def delete_role(role_id: int, db: Session = Depends(get_db)) -> ApiResponse:
    role = db.get(Role, role_id)
    if role is None or role.is_deleted:
        raise BusinessError("角色不存在", code=404)
    if role.is_system:
        raise BusinessError("系统内置角色不可删除", code=403)
    role.is_deleted = True
    db.commit()
    return ApiResponse.success(message="角色已删除")


@router.post(
    "/roles/{role_id}/permissions",
    response_model=ApiResponse[RoleOut],
    summary="分配角色权限",
    dependencies=[Depends(require_permissions("role:assign"))],
)
def assign_role_permissions(
    role_id: int, req: RolePermissionAssign, db: Session = Depends(get_db)
) -> ApiResponse:
    """为角色赋予权限（全量覆盖式）。"""
    role = db.get(Role, role_id)
    if role is None or role.is_deleted:
        raise BusinessError("角色不存在", code=404)
    perms = db.scalars(
        select(Permission).where(
            Permission.code.in_(req.permission_codes), Permission.is_deleted.is_(False)
        )
    ).all()
    if len(perms) != len(set(req.permission_codes)):
        raise BusinessError("存在无效的权限编码", code=400)
    role.permissions = perms
    db.commit()
    db.refresh(role)
    return ApiResponse.success(_role_out(role, db), message="权限分配成功")


@router.post(
    "/roles/{role_id}/departments",
    response_model=ApiResponse[RoleOut],
    summary="分配角色自定义数据范围部门",
    dependencies=[Depends(require_permissions("role:assign"))],
)
def assign_role_departments(
    role_id: int, req: RoleDeptAssign, db: Session = Depends(get_db)
) -> ApiResponse:
    """为 data_scope=2 的角色指定可见部门（全量覆盖式）。"""
    role = db.get(Role, role_id)
    if role is None or role.is_deleted:
        raise BusinessError("角色不存在", code=404)
    if role.data_scope != 2:
        raise BusinessError("仅 data_scope=2(自定义部门) 的角色可分配部门", code=400)
    dept_ids = req.dept_ids
    # 校验部门存在
    if dept_ids:
        exist = db.scalars(
            select(Department.id).where(
                Department.id.in_(dept_ids), Department.is_deleted.is_(False)
            )
        ).all()
        if set(exist) != set(dept_ids):
            raise BusinessError("存在无效的部门ID", code=400)
    _assign_role_depts(db, role.id, dept_ids)
    db.commit()
    db.refresh(role)
    return ApiResponse.success(_role_out(role, db), message="部门分配成功")


# ---------------------------------------------------------------------------
# 演示：超级管理员专用接口（验证 require_roles 中间件）
# ---------------------------------------------------------------------------


@router.get(
    "/system-health",
    response_model=ApiResponse[dict],
    summary="系统健康(仅超级管理员)",
    dependencies=[Depends(get_current_active_superuser)],
)
def system_health() -> ApiResponse:
    """仅超级管理员可访问，用于验证角色级访问控制。"""
    return ApiResponse.success({"status": "ok"}, message="超级管理员校验通过")

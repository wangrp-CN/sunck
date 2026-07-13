"""RBAC 初始数据播种：默认权限、角色与超级管理员。

幂等：按 code / username 存在性跳过，可重复执行。
用于首次部署或开发环境快速初始化。运行方式见 scripts/seed_rbac.py。
"""

from app.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.model.system import Department, Permission, Role, User, role_dept

# 模块（目录级，type=1）
_MODULES = [
    ("system", "系统管理", "/system", "setting"),
    ("project", "项目管理", "/project", "project"),
    ("device", "设备管理", "/device", "device"),
    ("person", "人员管理", "/person", "user"),
    ("machine", "机械管理", "/machine", "machine"),
    ("fence", "电子围栏", "/fence", "fence"),
    ("job", "作业计划", "/job", "plan"),
    ("alarm", "告警管理", "/alarm", "alert"),
    ("dashboard", "监控大屏", "/dashboard", "dashboard"),
]

# 各模块下的按钮/接口权限（type=3）
_CHILDREN = {
    "system": [
        "user:list",
        "user:add",
        "user:edit",
        "user:delete",
        "role:list",
        "role:add",
        "role:edit",
        "role:delete",
        "role:assign",
        "permission:list",
        "dept:list",
        "dept:add",
        "dept:edit",
        "dept:delete",
    ],
    "project": ["project:list", "project:add", "project:edit", "project:delete"],
    "device": ["device:list", "device:add", "device:edit"],
    "person": ["person:list", "person:add"],
    "machine": ["machine:list", "machine:add"],
    "fence": ["fence:list", "fence:add", "fence:edit"],
    "job": ["job:list", "job:add", "job:edit", "job:delete"],
    "alarm": ["alarm:list", "alarm:view", "alarm:handle", "alarm:config"],
    "dashboard": ["dashboard:view"],
}

# 角色 -> 权限编码集合
_ROLES = {
    "admin": {
        "name": "超级管理员",
        "is_system": True,
        "data_scope": 1,
        "codes": None,  # None 表示拥有全部权限
    },
    "project_manager": {
        "name": "项目经理",
        "is_system": False,
        "data_scope": 2,
        "codes": {
            "project:list",
            "project:add",
            "project:edit",
            "project:delete",
            "job:list",
            "job:add",
            "job:edit",
            "job:delete",
            "device:list",
            "device:add",
            "device:edit",
            "fence:list",
            "fence:add",
            "fence:edit",
            "alarm:list",
            "alarm:view",
            "alarm:handle",
            "alarm:config",
            "person:list",
            "person:add",
            "machine:list",
            "machine:add",
            "dashboard:view",
        },
        # 自定义数据范围（data_scope=2）绑定的部门编码；空表示不限定（看不到数据）
        "dept_codes": ["SECTION"],
    },
    "monitor": {
        "name": "监测员",
        "is_system": False,
        "data_scope": 3,
        "codes": {
            "device:list",
            "device:edit",
            "alarm:list",
            "alarm:view",
            "alarm:handle",
            "person:list",
            "machine:list",
            "fence:list",
            "job:list",
            "dashboard:view",
        },
    },
    "operator": {
        "name": "作业员",
        "is_system": False,
        "data_scope": 4,
        "codes": {"job:list", "job:add", "job:edit", "device:list", "dashboard:view"},
    },
    "guest": {
        "name": "访客",
        "is_system": False,
        "data_scope": 4,
        "codes": {"dashboard:view"},
    },
}

# 部门树（演示用）：集团 -> 工务段 -> 车间。parent_code 为 None 表示顶级。
_DEPARTMENTS = [
    ("HQ", "集团公司", None, 1),
    ("SECTION", "某工务段", "HQ", 2),
    ("WORKSHOP", "某车间", "SECTION", 3),
]


def seed_rbac(db=None) -> dict:
    """初始化 RBAC 数据。返回统计信息。"""
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        stats = {"permissions": 0, "roles": 0, "users": 0, "departments": 0}

        # 1) 模块（目录）
        module_objs: dict[str, Permission] = {}
        for code, name, path, icon in _MODULES:
            perm = db.scalar(select_perm(code))
            if perm is None:
                perm = Permission(name=name, code=code, type=1, path=path, icon=icon, status=True)
                db.add(perm)
                db.flush()
                stats["permissions"] += 1
            module_objs[code] = perm

        # 2) 子权限（按钮/接口）
        all_codes: list[str] = []
        for mod_code, child_codes in _CHILDREN.items():
            parent = module_objs[mod_code]
            for child_code in child_codes:
                all_codes.append(child_code)
                if db.scalar(select_perm(child_code)) is None:
                    perm = Permission(
                        name=child_code.split(":")[-1],
                        code=child_code,
                        type=3,
                        parent_id=parent.id,
                        status=True,
                    )
                    db.add(perm)
                    stats["permissions"] += 1
        db.flush()

        # 3) 角色
        perm_by_code = {
            p.code: p
            for p in db.scalars(select(Permission).where(Permission.is_deleted.is_(False))).all()
        }
        for role_code, spec in _ROLES.items():
            role = db.scalar(select_role(role_code))
            if role is None:
                role = Role(
                    name=spec["name"],
                    code=role_code,
                    is_system=spec["is_system"],
                    data_scope=spec["data_scope"],
                    status=True,
                )
                db.add(role)
                db.flush()
                stats["roles"] += 1
            # 分配权限（admin 拥有全部）
            if spec["codes"] is None:
                role.permissions = list(perm_by_code.values())
            else:
                role.permissions = [perm_by_code[c] for c in spec["codes"] if c in perm_by_code]

        # 3.5) 部门树（演示/数据范围基础数据）
        dept_by_code: dict[str, Department] = {}
        for code, name, parent_code, sort in _DEPARTMENTS:
            parent_id = dept_by_code[parent_code].id if parent_code else None
            dept = db.scalar(select_dept(code))
            if dept is None:
                dept = Department(name=name, code=code, parent_id=parent_id, sort=sort, status=True)
                db.add(dept)
                db.flush()
                stats["departments"] += 1
            dept_by_code[code] = dept

        # 3.6) 角色自定义数据范围（data_scope=2）：写入 role_dept
        for role_code, spec in _ROLES.items():
            dept_codes = spec.get("dept_codes")
            if not dept_codes:
                continue
            role = db.scalar(select_role(role_code))
            if role is None:
                continue
            existing = db.scalars(
                select(role_dept.c.dept_id).where(role_dept.c.role_id == role.id)
            ).all()
            if existing:
                continue
            for dc in dept_codes:
                d = dept_by_code.get(dc)
                if d is not None:
                    db.execute(role_dept.insert().values(role_id=role.id, dept_id=d.id))

        # 4) 超级管理员用户
        admin = db.scalar(select_user(settings.default_admin_username))
        if admin is None:
            admin_role = db.scalar(select_role("admin"))
            admin = User(
                username=settings.default_admin_username,
                password_hash=hash_password(settings.default_admin_password),
                nickname="系统管理员",
                is_superuser=True,
                status=True,
                roles=[admin_role] if admin_role else [],
            )
            db.add(admin)
            stats["users"] += 1

        db.commit()
        return stats
    finally:
        if own_session:
            db.close()


# 小工具：避免顶层 import 循环，使用局部 select
from sqlalchemy import select  # noqa: E402


def select_perm(code):
    return select(Permission).where(Permission.code == code, Permission.is_deleted.is_(False))


def select_dept(code):
    return select(Department).where(Department.code == code, Department.is_deleted.is_(False))


def select_role(code):
    return select(Role).where(Role.code == code, Role.is_deleted.is_(False))


def select_user(username):
    return select(User).where(User.username == username, User.is_deleted.is_(False))

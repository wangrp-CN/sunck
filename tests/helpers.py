"""集成测共享辅助：组织树 / 角色 / 用户创建与清理。

按 uid 前缀（T{u}）隔离测试自建数据，避免污染开发库。
各实体测试文件 import 本模块的函数，并复用 conftest 提供的
``client`` / ``admin_token`` 夹具。
"""

import secrets

from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.model.system import Department, Role, User, role_dept


def _uid() -> str:
    return secrets.token_hex(3)


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_dept(client, admin_token, u, code, parent_id=None):
    return client.post(
        "/api/v1/departments",
        headers=_headers(admin_token),
        json={"name": f"部门{code}", "code": f"T{u}_{code}", "parent_id": parent_id},
    ).json()["data"]


def _make_role(client, admin_token, u, code, perms, data_scope=3, dept_ids=None):
    role_code = f"T{u}_{code}"
    body = {"name": role_code, "code": role_code, "data_scope": data_scope, "remark": "test"}
    if dept_ids is not None:
        body["dept_ids"] = dept_ids
    role = client.post("/api/v1/auth/roles", headers=_headers(admin_token), json=body).json()[
        "data"
    ]
    client.post(
        f"/api/v1/auth/roles/{role['id']}/permissions",
        headers=_headers(admin_token),
        json={"permission_codes": perms},
    )
    return role


def _make_user(client, admin_token, u, username, role_code, dept_id):
    pw = "Test@123456"
    client.post(
        "/api/v1/auth/register",
        headers=_headers(admin_token),
        json={
            "username": username,
            "password": pw,
            "dept_id": dept_id,
            "role_codes": [role_code],
            "status": True,
        },
    )
    r = client.post("/api/v1/auth/login", json={"username": username, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


def _cleanup_org(u: str) -> None:
    """按 T{u} 前缀清理自建的角色 / 用户 / 部门（含部门树递归删除）。"""
    db = SessionLocal()
    try:
        role_ids = db.scalars(select(Role.id).where(Role.code.like(f"T{u}%"))).all()
        if role_ids:
            db.execute(role_dept.delete().where(role_dept.c.role_id.in_(role_ids)))
        db.execute(delete(User).where(User.username.like(f"T{u}%")))
        db.execute(delete(Role).where(Role.code.like(f"T{u}%")))
        # 部门树：先删叶子（非任何部门的父级），循环至无可删
        for _ in range(4):
            deleted = db.execute(
                delete(Department)
                .where(Department.code.like(f"T{u}%"))
                .where(
                    ~Department.id.in_(
                        select(Department.parent_id).where(Department.parent_id.is_not(None))
                    )
                )
            ).rowcount
            if deleted == 0:
                break
        db.commit()
    finally:
        db.close()

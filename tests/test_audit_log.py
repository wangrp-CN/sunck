"""操作审计模块测试。

- 服务层：写库 + 按数据范围检索（超级管理员可见全部，越权部门不可见）。
- 中间件：写请求自动落审计（受 settings.audit_enabled 控制）。
"""

import uuid

import pytest
from sqlalchemy import select

from app.config import settings
from app.core.data_scope import DataScope
from app.core.database import SessionLocal
from app.main import app
from app.model.audit import AuditLog
from app.model.system import Department, User
from app.service.audit_service import list_audit_logs, write_audit_log


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_audit_service_scoped(db_session):
    s = uuid.uuid4().hex[:8]
    admin_id = db_session.scalar(select(User.id).where(User.username == "admin"))
    da = Department(name=f"审A{s}", code=f"DA_{s}", status=True)
    db_session.add(da)
    db_session.flush()
    rec = write_audit_log(
        db_session,
        user_id=admin_id,
        username="admin",
        dept_id=da.id,
        action="create",
        module="devices",
        method="POST",
        path="/api/v1/devices",
        status_code=200,
    )
    db_session.commit()
    try:
        # 超级管理员可见全部
        page = list_audit_logs(db_session, DataScope(is_all=True))
        assert rec.id in {i.id for i in page.items}

        # 越权部门（未包含 da.id）不可见
        db_session.expire_all()
        page2 = list_audit_logs(db_session, DataScope(dept_ids={da.id + 1000}))
        assert rec.id not in {i.id for i in page2.items}

        # 命中本部门（da.id）可见
        page3 = list_audit_logs(db_session, DataScope(dept_ids={da.id}))
        assert rec.id in {i.id for i in page3.items}
    finally:
        db_session.delete(rec)
        db_session.delete(da)
        db_session.commit()


def test_audit_middleware_records_mutating_request():
    """中间件在写请求后落审计；测试结束清理并恢复开关。

    - 匿名登录（无 token）应被记录为匿名审计（username=None）；
    - 带 token 的写请求应捕获操作人 username（=admin）。
    """
    settings.audit_enabled = True
    created_ids = []
    created_dept_id = None
    db = SessionLocal()
    try:
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            # 匿名登录（写请求 POST，无 token）
            r = client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "Admin@123456"},
            )
            assert r.status_code == 200
            token = r.json()["data"]["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            # 带 token 的写请求：新建部门
            s = uuid.uuid4().hex[:8]
            r2 = client.post(
                "/api/v1/departments",
                json={"name": f"审计测试{s}", "code": f"AD_{s}"},
                headers=headers,
            )
            assert r2.status_code == 200
            created_dept_id = r2.json()["data"]["id"]

        # 匿名登录审计行存在（无操作人）
        login_rows = (
            db.query(AuditLog)
            .filter(AuditLog.path == "/api/v1/auth/login", AuditLog.module == "auth")
            .all()
        )
        assert login_rows, "中间件未写入匿名登录审计记录"
        assert login_rows[0].username is None
        created_ids += [x.id for x in login_rows]

        # 带 token 的写请求审计行捕获到操作人
        rows = (
            db.query(AuditLog)
            .filter(AuditLog.path == "/api/v1/departments", AuditLog.module == "departments")
            .all()
        )
        assert rows, "中间件未写入带 token 的审计记录"
        created_ids += [x.id for x in rows]
        row = rows[0]
        assert row.action == "create"
        assert row.method == "POST"
        assert row.status_code == 200
        assert row.username == "admin"
    finally:
        for rid in created_ids:
            obj = db.get(AuditLog, rid)
            if obj:
                db.delete(obj)
        if created_dept_id is not None:
            dept = db.get(Department, created_dept_id)
            if dept:
                db.delete(dept)
        db.commit()
        db.close()
        settings.audit_enabled = False

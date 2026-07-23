"""通知定向收敛回归测试。

验证 `resolve_recipients_for_project` / `notify_for_project` 确实按项目数据范围
收敛接收人，修复此前「向全部活跃用户广播」与部门数据隔离冲突的问题。
"""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.notify import notify_for_project, resolve_recipients_for_project
from app.model.notification import Notification
from app.model.project import Project
from app.model.system import Department, Role, User


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def _make_user(db: Session, username: str, dept_id, role: Role, superuser=False) -> User:
    u = User(
        username=username,
        nickname=username,
        password_hash="dummy_hash_not_used",
        dept_id=dept_id,
        status=True,
        is_superuser=superuser,
    )
    u.roles.append(role)
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def scope_fixture():
    """构建：超级管理员 + 同部门用户 + 异部门用户 + 仅本人用户 + 一个项目。"""
    s = _suffix()
    db = SessionLocal()
    created = []
    try:
        dept_x = Department(name=f"项目部X{s}", code=f"DEPT_X_{s}", parent_id=None, status=True)
        dept_y = Department(name=f"项目部Y{s}", code=f"DEPT_Y_{s}", parent_id=None, status=True)
        db.add_all([dept_x, dept_y])
        db.flush()

        role_dept3 = Role(name=f"本部门角色{s}", code=f"ROLE_DEPT3_{s}", data_scope=3, status=True)
        role_self = Role(name=f"仅本人角色{s}", code=f"ROLE_SELF_{s}", data_scope=4, status=True)
        db.add_all([role_dept3, role_self])
        db.flush()

        super_u = _make_user(db, f"su_{s}", None, role_dept3, superuser=True)
        same_u = _make_user(db, f"same_{s}", dept_x.id, role_dept3)
        other_u = _make_user(db, f"other_{s}", dept_y.id, role_dept3)
        self_u = _make_user(db, f"self_{s}", dept_x.id, role_self)

        proj = Project(name=f"通知收敛测试项目{s}", dept_id=dept_x.id, status=True)
        db.add(proj)
        db.flush()

        db.commit()
        created = [proj, self_u, other_u, same_u, super_u, role_self, role_dept3, dept_y, dept_x]
        yield {
            "super": super_u,
            "same": same_u,
            "other": other_u,
            "self": self_u,
            "project": proj,
        }
    finally:
        # 反向顺序删除（先子后父），避免外键约束导致清理失败残留
        for obj in reversed(created):
            db.delete(obj)
        db.commit()
        db.close()


def test_resolve_recipients_scoped(scope_fixture):
    db = SessionLocal()
    try:
        rec = resolve_recipients_for_project(db, scope_fixture["project"].id)
        # 超级管理员恒接收
        assert scope_fixture["super"].id in rec
        # 同部门（本部门及以下）用户接收
        assert scope_fixture["same"].id in rec
        # 异部门用户不应接收（数据隔离）
        assert scope_fixture["other"].id not in rec
        # 仅本人用户不应接收跨用户的广播通知
        assert scope_fixture["self"].id not in rec
    finally:
        db.close()


def test_resolve_recipients_no_project_only_superuser(scope_fixture):
    """项目无归属部门时，仅「全部数据」用户（超级管理员）接收，不向无权部门扩散。"""
    db = SessionLocal()
    try:
        rec = resolve_recipients_for_project(db, None)
        assert scope_fixture["super"].id in rec
        assert scope_fixture["same"].id not in rec
        assert scope_fixture["other"].id not in rec
    finally:
        db.close()


def test_notify_for_project_writes_only_to_recipients(scope_fixture):
    """实际下发：通知行只写给范围内用户。"""
    db = SessionLocal()
    try:
        before = db.query(Notification).count()
        n = notify_for_project(
            db,
            scope_fixture["project"].id,
            "测试告警通知",
            content="x",
            link="/alarms",
            category="alarm",
        )
        db.commit()
        after = db.query(Notification).count()
        # 接收人数 = 落库通知数（单渠道 in_app）
        assert after - before == n
        # 异部门用户不应收到
        other_cnt = (
            db.query(Notification).filter(Notification.user_id == scope_fixture["other"].id).count()
        )
        assert other_cnt == 0
        # 同部门用户收到
        same_cnt = (
            db.query(Notification).filter(Notification.user_id == scope_fixture["same"].id).count()
        )
        assert same_cnt == 1
    finally:
        db.close()

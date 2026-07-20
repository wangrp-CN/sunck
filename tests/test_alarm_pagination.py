"""告警列表真分页回归测试（对应优化项 #13「告警列表无分页」）。

覆盖：
- count_alarms 返回真实总数（不受 page/size 限制），可超过旧的 200 上限；
- list_alarms 按 page/size offset 分页，页内条数正确；
- 相邻两页 id 不重叠、且按 (alarm_time desc, id desc) 稳定排序；
- 过滤条件（project_id）在 list/count 上一致生效。

为隔离共享开发库，所有断言均限定在本测试临时创建的 project 下，
并按 project_id 清理自建告警。
"""

import secrets

import pytest
from sqlalchemy import delete

from app.core.data_scope import DataScope
from app.core.database import SessionLocal
from app.model.alarm import Alarm
from app.model.project import Project
from app.service.alarm_service import count_alarms, list_alarms

_N = 25  # 超过单页 size，便于验证跨页


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def seeded_project(db_session):
    """创建 1 个临时项目 + N 条告警，返回 (project_id, [alarm_id...])。"""
    proj = Project(name=f"PGP-{secrets.token_hex(3)}")
    db_session.add(proj)
    db_session.flush()
    ids = []
    for i in range(_N):
        a = Alarm(
            project_id=proj.id,
            alarm_type="fence_intrusion",
            device_no=f"PG-{i:03d}",
            alarm_info=f"分页测试告警 {i}",
            alarm_status="告警开始",
            handle_status="待处理",
        )
        db_session.add(a)
        db_session.flush()
        ids.append(a.id)
    db_session.commit()
    yield proj.id, ids
    db_session.execute(delete(Alarm).where(Alarm.project_id == proj.id))
    db_session.execute(delete(Project).where(Project.id == proj.id))
    db_session.commit()


def test_count_returns_real_total(db_session, seeded_project):
    """count_alarms 返回真实总数（不受分页 size 限制）。"""
    pid, _ = seeded_project
    scope = DataScope(is_all=True)
    total = count_alarms(db_session, scope, project_id=pid)
    assert total == _N, total


def test_list_paginates_and_no_overlap(db_session, seeded_project):
    """list_alarms 按 page/size 分页，页内条数正确且相邻页不重叠。"""
    pid, _ = seeded_project
    scope = DataScope(is_all=True)

    size = 10
    p1 = list_alarms(db_session, scope, project_id=pid, page=1, size=size)
    p2 = list_alarms(db_session, scope, project_id=pid, page=2, size=size)
    p3 = list_alarms(db_session, scope, project_id=pid, page=3, size=size)

    assert len(p1) == 10
    assert len(p2) == 10
    assert len(p3) == 5  # 25 = 10 + 10 + 5

    ids1 = {r["id"] for r in p1}
    ids2 = {r["id"] for r in p2}
    ids3 = {r["id"] for r in p3}
    # 三页两两无交集
    assert not (ids1 & ids2)
    assert not (ids2 & ids3)
    assert not (ids1 & ids3)
    # 三页并集 == 全量
    assert len(ids1 | ids2 | ids3) == _N


def test_list_stable_order_desc(db_session, seeded_project):
    """整表按 id 降序稳定排序（alarm_time 相同的降级排序键）。"""
    pid, _ = seeded_project
    scope = DataScope(is_all=True)
    allrows = list_alarms(db_session, scope, project_id=pid, page=1, size=_N)
    got_ids = [r["id"] for r in allrows]
    assert got_ids == sorted(got_ids, reverse=True), got_ids


def test_page_out_of_range_returns_empty(db_session, seeded_project):
    """超出范围的页码返回空列表，但 total 仍为真实总数。"""
    pid, _ = seeded_project
    scope = DataScope(is_all=True)
    total = count_alarms(db_session, scope, project_id=pid)
    rows = list_alarms(db_session, scope, project_id=pid, page=999, size=10)
    assert total == _N
    assert rows == []

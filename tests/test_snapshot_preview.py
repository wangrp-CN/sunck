"""快照预览端点回归 + 数据隔离测试。

覆盖：
- GET /v1/alarms/snapshot/preview 结构正确（granularity/period_keys/summary/periods/project_summary）
- 自洽：Σperiods.total == summary.total == Σproject_summary.count；ratio 合计≈1；
  每个周期 by_type 之和 == 该周期 total
- 缺 start/end → code=400；非法粒度 → code=400
- 部门数据隔离：data_scope=3（本部门及以下）用户仅见其归属部门项目的告警，
  预览 total 与其可见告警数一致；超管见全部（含其它部门项目）。

按 uid 清理自建数据，避免污染开发库。
"""

import secrets
from datetime import datetime, timezone
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.v1 import alarms as alarms_module
from app.core.database import SessionLocal
from app.main import app
from app.model.alarm import Alarm
from app.model.project import Project
from app.model.system import Department, Role, User, role_dept


def _uid() -> str:
    return secrets.token_hex(3)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_token(client):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin@123456"})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _cleanup(u: str) -> None:
    db = SessionLocal()
    try:
        role_ids = db.scalars(select(Role.id).where(Role.code.like(f"T{u}%"))).all()
        if role_ids:
            db.execute(role_dept.delete().where(role_dept.c.role_id.in_(role_ids)))
        db.execute(delete(Project).where(Project.name.like(f"P{u}%")))
        db.execute(delete(User).where(User.username.like(f"T{u}%")))
        db.execute(delete(Role).where(Role.code.like(f"T{u}%")))
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


def _make_role(client, admin_token, u, code, data_scope, perms, dept_ids=None):
    body = {"name": code, "code": code, "data_scope": data_scope, "remark": "test"}
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


def _make_user(client, admin_token, u, username, role_code, dept_id, password="Test@123456"):
    body = {
        "username": username,
        "nickname": username,
        "password": password,
        "dept_id": dept_id,
        "role_codes": [role_code],
        "status": True,
    }
    r = client.post("/api/v1/auth/register", headers=_headers(admin_token), json=body)
    assert r.status_code == 200, r.text
    lr = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert lr.status_code == 200, lr.text
    return lr.json()["data"]["access_token"]


def _create_project(client, token, u, name, dept_id):
    r = client.post(
        "/api/v1/projects",
        headers=_headers(token),
        json={"name": f"P{u}_{name}", "dept_id": dept_id, "status": "在建"},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _insert_alarms(db, pid, points, atype="fence_intrusion", level="严重"):
    objs = []
    for y, m, d, hh in points:
        objs.append(
            Alarm(
                project_id=pid,
                alarm_type=atype,
                device_type="locate",
                device_name="定位工牌",
                device_no=f"SNAP-{y}{m}{d}-{hh}",
                alarm_info="SNAP_PREVIEW_SEED",
                alarm_status="告警开始",
                alarm_level=level,
                handle_status="待处理",
                alarm_time=datetime(y, m, d, hh, 0, 0, tzinfo=timezone.utc),
            )
        )
    db.add_all(objs)
    db.commit()


def test_snapshot_preview_structure_and_consistency(client, admin_token):
    """预览结构正确 + 内部自洽（不依赖绝对告警数）。"""
    u = _uid()
    db = SessionLocal()
    pid = None
    try:
        proj = Project(name=f"P{u}_prev", status="在建")
        db.add(proj)
        db.flush()
        pid = proj.id
        points = [
            (2026, 5, 10, 9),
            (2026, 5, 20, 14),
            (2026, 5, 28, 20),
            (2026, 6, 5, 10),
            (2026, 6, 15, 16),
            (2026, 6, 25, 8),
            (2026, 7, 3, 11),
            (2026, 7, 12, 13),
        ]
        _insert_alarms(db, pid, points)
        expected = len(points)

        r = client.get(
            "/api/v1/alarms/snapshot/preview",
            headers=_headers(admin_token),
            params={
                "granularity": "month",
                "project_id": pid,
                "start": "2026-05-01T00:00:00",
                "end": "2026-07-31T23:59:59",
            },
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["code"] == 0, d
        p = d["data"]
        # 结构
        assert p["granularity"] == "month"
        assert set(p["period_keys"]) == {"2026-05", "2026-06", "2026-07"}, p["period_keys"]
        assert len(p["periods"]) == 3
        for x in p["periods"]:
            assert set(x.keys()) >= {
                "period",
                "total",
                "by_type",
                "by_level",
                "pending",
                "handled",
                "by_project",
            }
            # 周期内部自洽：by_type 之和 == total（缺失类型按 0 计）
            assert sum(x["by_type"].values()) == x["total"], x
        # 跨块自洽
        assert p["summary"]["total"] == expected, p["summary"]
        assert sum(x["total"] for x in p["periods"]) == expected
        assert sum(x["count"] for x in p["project_summary"]) == expected
        # 按项目明细（与 Excel 分 sheet / PDF 分节同源）：行数之和==总数
        assert "projects_detail" in p, p.keys()
        assert sum(x["count"] for x in p["projects_detail"]) == expected
        for pd in p["projects_detail"]:
            assert {"project_name", "count", "capped", "rows"} <= set(pd.keys())
            if not pd["capped"]:
                assert len(pd["rows"]) == pd["count"], pd["project_name"]
        # 占比合计≈1
        assert abs(sum(x["ratio"] for x in p["project_summary"]) - 1.0) < 1e-9
    finally:
        if pid is not None:
            db.execute(delete(Alarm).where(Alarm.project_id == pid))
            db.execute(delete(Project).where(Project.id == pid))
            db.commit()
        db.close()
        _cleanup(u)


def test_snapshot_preview_required_range(client, admin_token):
    """缺 start 或 end → code=400。"""
    r1 = client.get(
        "/api/v1/alarms/snapshot/preview",
        headers=_headers(admin_token),
        params={"granularity": "month", "start": "2026-05-01T00:00:00"},
    )
    assert r1.json()["code"] == 400, r1.text
    r2 = client.get(
        "/api/v1/alarms/snapshot/preview",
        headers=_headers(admin_token),
        params={"granularity": "month", "end": "2026-07-31T23:59:59"},
    )
    assert r2.json()["code"] == 400, r2.text


def test_snapshot_preview_invalid_gran(client, admin_token):
    """非法粒度 → code=400。"""
    r = client.get(
        "/api/v1/alarms/snapshot/preview",
        headers=_headers(admin_token),
        params={
            "granularity": "year",
            "start": "2026-05-01T00:00:00",
            "end": "2026-07-31T23:59:59",
        },
    )
    assert r.json()["code"] == 400, r.text


def test_snapshot_preview_data_isolation(client, admin_token):
    """部门数据隔离：data_scope=3（本部门及以下）用户仅见其部门项目的告警。

    部门树 HQ -> SEC -> WS；P_SEC 在 SEC，P_HQ 在 HQ（非 SEC 下级）。
    SEC 用户（归属 SEC）应只看到 P_SEC 的 4 条告警；超管看到 P_SEC(4)+P_HQ(3)=7。
    """
    u = _uid()
    db = SessionLocal()
    pid_sec = pid_hq = None
    try:
        hq = client.post(
            "/api/v1/departments",
            headers=_headers(admin_token),
            json={"name": "测试集团", "code": f"T{u}_HQ", "parent_id": None},
        ).json()["data"]
        sec = client.post(
            "/api/v1/departments",
            headers=_headers(admin_token),
            json={"name": "测试段", "code": f"T{u}_SEC", "parent_id": hq["id"]},
        ).json()["data"]
        client.post(
            "/api/v1/departments",
            headers=_headers(admin_token),
            json={"name": "测试车间", "code": f"T{u}_WS", "parent_id": sec["id"]},
        ).json()["data"]

        r_sec = _make_role(
            client,
            admin_token,
            u,
            f"T{u}_SEC3",
            3,
            ["alarm:list"],
            dept_ids=[sec["id"]],
        )
        proj_sec = _create_project(client, admin_token, u, "sec", sec["id"])
        proj_hq = _create_project(client, admin_token, u, "hq", hq["id"])
        pid_sec, pid_hq = proj_sec["id"], proj_hq["id"]

        # P_SEC 4 条（6 月），P_HQ 3 条（6 月）
        _insert_alarms(
            db, pid_sec, [(2026, 6, 5, 9), (2026, 6, 12, 14), (2026, 6, 18, 20), (2026, 6, 25, 8)]
        )
        _insert_alarms(db, pid_hq, [(2026, 6, 6, 10), (2026, 6, 14, 16), (2026, 6, 22, 8)])

        sec_token = _make_user(client, admin_token, u, f"T{u}_u", r_sec["code"], sec["id"])

        # SEC 用户预览（窗口 6 月）
        r_sec_prev = client.get(
            "/api/v1/alarms/snapshot/preview",
            headers=_headers(sec_token),
            params={
                "granularity": "month",
                "start": "2026-06-01T00:00:00",
                "end": "2026-06-30T23:59:59",
            },
        )
        assert r_sec_prev.status_code == 200, r_sec_prev.text
        ps = r_sec_prev.json()["data"]
        sec_names = {x["project_name"] for x in ps["project_summary"]}
        assert sec_names == {proj_sec["name"]}, sec_names
        assert ps["summary"]["total"] == 4, ps["summary"]
        assert sum(x["total"] for x in ps["periods"]) == 4
        assert abs(sum(x["ratio"] for x in ps["project_summary"]) - 1.0) < 1e-9

        # 超管预览：应同时看到 P_SEC 与 P_HQ
        r_adm_prev = client.get(
            "/api/v1/alarms/snapshot/preview",
            headers=_headers(admin_token),
            params={
                "granularity": "month",
                "start": "2026-06-01T00:00:00",
                "end": "2026-06-30T23:59:59",
            },
        )
        pa = r_adm_prev.json()["data"]
        adm_names = {x["project_name"] for x in pa["project_summary"]}
        assert proj_sec["name"] in adm_names and proj_hq["name"] in adm_names, adm_names
        # 超管总数 == 7（seed 历史告警也在 6 月，但本项目只断言 >= 两个项目之和）
        sec_in_adm = next(x for x in pa["project_summary"] if x["project_name"] == proj_sec["name"])
        hq_in_adm = next(x for x in pa["project_summary"] if x["project_name"] == proj_hq["name"])
        assert sec_in_adm["count"] == 4, sec_in_adm
        assert hq_in_adm["count"] == 3, hq_in_adm
    finally:
        for pid in (pid_sec, pid_hq):
            if pid is not None:
                db.execute(delete(Alarm).where(Alarm.project_id == pid))
        db.commit()
        db.close()
        _cleanup(u)


def test_snapshot_empty_period_preserved(client, admin_token):
    """空周期不能丢：窗口跨 3 个月但仅首/末月有告警，中间月 total 须为 0 且仍出现在 period_keys。"""
    u = _uid()
    db = SessionLocal()
    pid = None
    try:
        proj = Project(name=f"P{u}_empty", status="在建")
        db.add(proj)
        db.flush()
        pid = proj.id
        # 仅 5 月与 7 月有告警，6 月为空
        _insert_alarms(db, pid, [(2026, 5, 10, 9), (2026, 5, 20, 14)])
        _insert_alarms(db, pid, [(2026, 7, 3, 11), (2026, 7, 12, 13)])
        expected = 4

        r = client.get(
            "/api/v1/alarms/snapshot/preview",
            headers=_headers(admin_token),
            params={
                "granularity": "month",
                "project_id": pid,
                "start": "2026-05-01T00:00:00",
                "end": "2026-07-31T23:59:59",
            },
        )
        assert r.status_code == 200, r.text
        p = r.json()["data"]
        # 三个月都在（含空周期 6 月）
        assert set(p["period_keys"]) == {"2026-05", "2026-06", "2026-07"}, p["period_keys"]
        assert len(p["periods"]) == 3
        by_period = {x["period"]: x["total"] for x in p["periods"]}
        assert by_period["2026-05"] == 2
        assert by_period["2026-06"] == 0, "空周期必须保留且 total=0"
        assert by_period["2026-07"] == 2
        assert p["summary"]["total"] == expected, p["summary"]
        assert sum(x["total"] for x in p["periods"]) == expected
    finally:
        if pid is not None:
            db.execute(delete(Alarm).where(Alarm.project_id == pid))
            db.execute(delete(Project).where(Project.id == pid))
            db.commit()
        db.close()
        _cleanup(u)


def test_compute_snapshot_single_query():
    """#6 回归：_compute_snapshot 对多周期只发 1 次查询（而非 N 次）。

    用 12 个月窗口 + 月度粒度（应枚举 12 个周期），mock query_alarms_for_report，
    断言其仅被调用一次，且返回的 period_keys 仍为 12 个（含空桶）。
    """
    from app.api.v1.alarms import _compute_snapshot

    fake_rows = [
        {
            "alarm_time": datetime(2026, 1, 15, 9, 0, 0, tzinfo=timezone.utc).isoformat(),
            "project_id": 1,
            "alarm_type": "fence_intrusion",
            "alarm_level": "严重",
            "handle_status": "待处理",
        },
        {
            "alarm_time": datetime(2026, 12, 20, 9, 0, 0, tzinfo=timezone.utc).isoformat(),
            "project_id": 1,
            "alarm_type": "device_alarm",
            "alarm_level": "一般",
            "handle_status": "已处理",
        },
    ]
    db = mock.MagicMock()
    # 项目名映射查询：db.execute(...).all() 返回 [(id, name)]
    db.execute.return_value.all.return_value = [(1, "P1")]

    with mock.patch.object(alarms_module, "query_alarms_for_report", return_value=fake_rows) as m:
        period_keys, period_rows, summary, project_names, meta = _compute_snapshot(
            db,
            mock.MagicMock(is_all=True),
            "month",
            datetime(2026, 1, 1),
            datetime(2026, 12, 31, 23, 59, 59),
            "2026-01-01T00:00:00",
            "2026-12-31T23:59:59",
        )
        # 关键断言：12 个月只发 1 次整窗查询
        assert m.call_count == 1, f"期望 1 次查询，实际 {m.call_count} 次"
        # 返回的 period_keys 为完整 12 个月（含无告警的空桶）
        assert len(period_keys) == 12, period_keys
        assert all(pk in period_rows for pk in period_keys)
        # summary 仅含两条 seed 告警
        assert summary["total"] == 2, summary
        # 两条告警正确分桶到 2026-01 与 2026-12
        assert len(period_rows["2026-01"]) == 1
        assert len(period_rows["2026-12"]) == 1
        # 项目名映射正常
        assert project_names == {1: "P1"}

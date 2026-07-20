"""Dashboard 部门数据隔离 · 端到端测试。

复用仓库既有 fixtures（TestClient + 真实数据库）。验证：
  1) 超管 / data_scope==1 可见全部项目；
  2) data_scope==3（本部门及以下）用户仅见其归属部门（及下级）的项目；
  3) /recent-alarms 同样按数据范围过滤（超管条数 >= 部门用户条数）。

测试结束按 uid 清理自建数据，避免污染开发库。
"""

import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.main import app
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
    # 登录换取 token
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


def test_dashboard_scope_isolation(client, admin_token):
    u = _uid()
    try:
        # 部门树：HQ -> SEC -> WS
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
        _ws = client.post(
            "/api/v1/departments",
            headers=_headers(admin_token),
            json={"name": "测试车间", "code": f"T{u}_WS", "parent_id": sec["id"]},
        ).json()["data"]

        # 角色：本部门及以下(3) + 需 dashboard:view/project:list/project:add
        r_sec = _make_role(
            client,
            admin_token,
            u,
            f"T{u}_SEC3",
            3,
            ["dashboard:view", "project:list", "project:add"],
            dept_ids=[sec["id"]],
        )

        # 超管建两个项目：一个在 SEC，一个在 HQ（非 SEC 下级）
        _admin_proj_sec = _create_project(client, admin_token, u, "admin_sec", sec["id"])
        _admin_proj_hq = _create_project(client, admin_token, u, "admin_hq", hq["id"])

        # 部门用户登录（归属 SEC：本部门及以下 => {SEC, WS}）
        sec_token = _make_user(client, admin_token, u, f"T{u}_u", r_sec["code"], sec["id"])

        admin_stats = client.get("/api/v1/dashboard/stats", headers=_headers(admin_token)).json()[
            "data"
        ]["counts"]
        sec_stats = client.get("/api/v1/dashboard/stats", headers=_headers(sec_token)).json()[
            "data"
        ]["counts"]

        # 超管见全部 2 个项目；WS 用户的本部门(WS)+下级 不含 HQ => 仅 1 个
        assert admin_stats["projects"] >= 2, admin_stats
        assert sec_stats["projects"] == 1, sec_stats
        assert sec_stats["projects"] < admin_stats["projects"], (sec_stats, admin_stats)
    finally:
        _cleanup(u)


def test_dashboard_recent_alarms_scoped(client, admin_token):
    u = _uid()
    try:
        hq = client.post(
            "/api/v1/departments",
            headers=_headers(admin_token),
            json={"name": "测试集团", "code": f"T{u}_HQ", "parent_id": None},
        ).json()["data"]
        ws = client.post(
            "/api/v1/departments",
            headers=_headers(admin_token),
            json={"name": "测试车间", "code": f"T{u}_WS", "parent_id": hq["id"]},
        ).json()["data"]
        r_ws = _make_role(
            client,
            admin_token,
            u,
            f"T{u}_WS3",
            3,
            ["dashboard:view"],
            dept_ids=[ws["id"]],
        )
        ws_token = _make_user(client, admin_token, u, f"T{u}_wu", r_ws["code"], ws["id"])

        admin_al = client.get(
            "/api/v1/dashboard/recent-alarms", headers=_headers(admin_token)
        ).json()["data"]
        ws_al = client.get("/api/v1/dashboard/recent-alarms", headers=_headers(ws_token)).json()[
            "data"
        ]
        # 部门用户可见告警数不应超过超管
        assert ws_al["total"] <= admin_al["total"], (ws_al, admin_al)
    finally:
        _cleanup(u)


def test_dashboard_stats_period_linked(client, admin_token):
    """验证 /stats 的 granularity/start/end 周期联动：趋势按窗口分桶。

    测试库与演示库共用同一 PG，存在 seed 历史数据，故用「插入前后差值」做断言，
    隔离预置数据干扰，只校验本测试写入的 3 条告警是否落入正确周期。
    """
    from datetime import datetime

    from app.model.alarm import Alarm as AlarmModel

    def _month_counts():
        r = client.get(
            "/api/v1/dashboard/stats",
            headers=_headers(admin_token),
            params={
                "granularity": "month",
                "start": "2026-05-01T00:00:00",
                "end": "2026-06-30T23:59:59",
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        return (
            {p["period"]: p["count"] for p in data["alarm_trend_period"]},
            data["trend_granularity"],
            data["trend_start"],
            data["trend_end"],
        )

    u = _uid()
    pid = None
    try:
        proj = _create_project(client, admin_token, u, "trend", 1)
        pid = proj["id"]

        # 插入前基线
        before, gran, ts, te = _month_counts()
        assert gran == "month" and ts == "2026-05-01" and te == "2026-06-30"

        db = SessionLocal()
        try:
            db.add_all(
                [
                    AlarmModel(
                        project_id=pid,
                        alarm_type="fence_intrusion",
                        device_type="anti_intrusion",
                        device_no="T-1",
                        alarm_level="严重",
                        handle_status="待处理",
                        alarm_time=datetime(2026, 5, 15, 10, 0, 0),
                        alarm_info="x",
                    ),
                    AlarmModel(
                        project_id=pid,
                        alarm_type="device_alarm",
                        device_type="locate",
                        device_no="T-2",
                        alarm_level="提示",
                        handle_status="待处理",
                        alarm_time=datetime(2026, 6, 20, 10, 0, 0),
                        alarm_info="y",
                    ),
                    AlarmModel(
                        project_id=pid,
                        alarm_type="distance_too_close",
                        device_type="anti_intrusion",
                        device_no="T-3",
                        alarm_level="警告",
                        handle_status="待处理",
                        alarm_time=datetime(2026, 6, 25, 10, 0, 0),
                        alarm_info="z",
                    ),
                ]
            )
            db.commit()
        finally:
            db.close()

        # 插入后：2026-05 增 1、2026-06 增 2
        after, _, _, _ = _month_counts()
        assert after.get("2026-05", 0) - before.get("2026-05", 0) == 1, (before, after)
        assert after.get("2026-06", 0) - before.get("2026-06", 0) == 2, (before, after)

        # 级别/处置分布卡随周期联动：其合计应与窗口告警总数 alarms_window 自洽
        rd = client.get(
            "/api/v1/dashboard/stats",
            headers=_headers(admin_token),
            params={
                "granularity": "month",
                "start": "2026-05-01T00:00:00",
                "end": "2026-06-30T23:59:59",
            },
        ).json()["data"]
        lv_sum = sum(x["count"] for x in rd["alarm_by_level"])
        hd_sum = sum(x["count"] for x in rd["alarm_by_handle"])
        assert lv_sum == rd["counts"]["alarms_window"], (lv_sum, rd["counts"]["alarms_window"])
        assert hd_sum == rd["counts"]["alarms_window"], (hd_sum, rd["counts"]["alarms_window"])

        # 周粒度：2026-05-15 落在 ISO 周 W20（周一 2026-05-11）
        r2 = client.get(
            "/api/v1/dashboard/stats",
            headers=_headers(admin_token),
            params={
                "granularity": "week",
                "start": "2026-05-11T00:00:00",
                "end": "2026-05-17T23:59:59",
            },
        )
        p2 = {x["period"]: x["count"] for x in r2.json()["data"]["alarm_trend_period"]}
        assert p2.get("2026-W20", 0) >= 1, p2
    finally:
        if pid is not None:
            db = SessionLocal()
            try:
                db.execute(delete(AlarmModel).where(AlarmModel.project_id == pid))
                db.commit()
            finally:
                db.close()
        _cleanup(u)


def test_dashboard_stats_window_and_current_period(client, admin_token):
    """验证计数卡周期联动字段与趋势桶自洽（不依赖绝对告警数）：
    - counts.alarms_window == 各周期桶计数之和；
    - counts.alarms_current_period == data.current_period 对应桶的计数（空桶记 0）；
    - current_period 的 key 格式与 granularity 匹配。
    """
    for gran in ("day", "week", "month"):
        r = client.get(
            "/api/v1/dashboard/stats",
            headers=_headers(admin_token),
            params={
                "granularity": gran,
                "start": "2026-05-01T00:00:00",
                "end": "2026-07-31T23:59:59",
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        buckets = {p["period"]: p["count"] for p in data["alarm_trend_period"]}
        counts = data["counts"]

        # 窗口合计 == 各周期桶之和
        assert counts["alarms_window"] == sum(buckets.values()), (gran, counts, buckets)
        # 本周期告警 == 当前周期桶（不存在则 0）
        cur = data["current_period"]
        assert counts["alarms_current_period"] == buckets.get(cur, 0), (gran, cur, counts, buckets)
        # current_period key 格式匹配粒度
        if gran == "month":
            assert len(cur) == 7 and cur[4] == "-", cur  # YYYY-MM
        elif gran == "week":
            assert "-W" in cur, cur  # YYYY-Www
        else:
            assert len(cur) == 10 and cur.count("-") == 2, cur  # YYYY-MM-DD


def test_dashboard_stats_device_fence(client, admin_token):
    """验证 /stats 新增 device_stats（在线率/区间活跃）与 fence_stats（窗口内监控围栏）
    均随所选时间窗周期联动，且字段自洽。

    - device_stats：online_rate ∈ [0,100]；online ≤ total；远过去窗口(2020)内无上报 → window_active==0。
    - fence_stats：窗口内监控围栏数随窗口变化——插入一个「仅在 2030 激活」的计划+围栏，
      在同时覆盖种子计划(2026~2027)与未来计划(2030)的宽窗口 [2026-01-01,2030-12-31] 内，
      监控围栏数应为插入前 +1（delta 隔离预置数据，证明窗口约束生效）。
    """
    from datetime import datetime

    from app.model.fence import ElectronicFence
    from app.model.job import WorkPlan, WorkPlanFence

    u = _uid()
    pid = None
    plan_id = None
    fence_id = None
    try:
        # 基础字段与自洽
        r = client.get("/api/v1/dashboard/stats", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        ds = d["device_stats"]
        fs = d["fence_stats"]
        assert set(ds.keys()) >= {"total", "online", "online_rate", "window_active"}, ds
        assert set(fs.keys()) >= {"total", "enabled", "monitored_in_window", "by_type"}, fs
        assert 0 <= ds["online_rate"] <= 100, ds
        assert ds["online"] <= ds["total"], ds
        assert ds["window_active"] >= 0 and fs["monitored_in_window"] >= 0

        # 远过去窗口（2020）：无设备上报 → window_active 必须为 0（窗口过滤生效）
        r2020 = client.get(
            "/api/v1/dashboard/stats",
            headers=_headers(admin_token),
            params={
                "granularity": "month",
                "start": "2020-01-01T00:00:00",
                "end": "2020-12-31T23:59:59",
            },
        ).json()["data"]
        assert r2020["device_stats"]["window_active"] == 0, r2020["device_stats"]

        # 宽窗口基准（含种子计划 2026~2027 与未来计划 2030），插入前计数
        WIDE = {
            "granularity": "month",
            "start": "2026-01-01T00:00:00",
            "end": "2030-12-31T23:59:59",
        }
        base_mon = client.get(
            "/api/v1/dashboard/stats", headers=_headers(admin_token), params=WIDE
        ).json()["data"]["fence_stats"]["monitored_in_window"]

        # 建一个仅在 2030 激活的计划 + 围栏
        proj = _create_project(client, admin_token, u, "fence", 1)
        pid = proj["id"]
        db = SessionLocal()
        try:
            fence = ElectronicFence(
                project_id=pid,
                name=f"F{u}",
                fence_type="test",
                enabled=True,
                geometry_wkt="POLYGON((0 0,0 1,1 1,1 0,0 0))",
                is_deleted=False,
            )
            db.add(fence)
            db.flush()
            fence_id = fence.id
            plan = WorkPlan(
                project_id=pid,
                name=f"P{u}_2030",
                is_start=True,
                status="执行中",
                plan_start=datetime(2030, 1, 1),
                plan_end=datetime(2030, 12, 31),
                is_deleted=False,
            )
            db.add(plan)
            db.flush()
            plan_id = plan.id
            db.add(WorkPlanFence(plan_id=plan_id, fence_id=fence_id))
            db.commit()
        finally:
            db.close()

        # 同一宽窗口：未来计划落入 → 监控围栏数 = 插入前 + 1（delta 隔离预置数据）
        after_mon = client.get(
            "/api/v1/dashboard/stats", headers=_headers(admin_token), params=WIDE
        ).json()["data"]["fence_stats"]["monitored_in_window"]
        assert after_mon == base_mon + 1, (base_mon, after_mon)
    finally:
        db = SessionLocal()
        try:
            if plan_id is not None:
                db.execute(delete(WorkPlanFence).where(WorkPlanFence.plan_id == plan_id))
                db.execute(delete(WorkPlan).where(WorkPlan.id == plan_id))
            if pid is not None:
                db.execute(delete(ElectronicFence).where(ElectronicFence.project_id == pid))
            db.commit()
        finally:
            db.close()
        _cleanup(u)


def test_alarm_handle_scoped(client, admin_token):
    """验证告警处置端点实施部门数据隔离：跨部门不可处置（应 404）。"""
    from datetime import datetime

    from app.model.alarm import Alarm as AlarmModel

    u = _uid()
    db = SessionLocal()
    p_sec_id: int | None = None
    p_hq_id: int | None = None
    a_vis_id: int | None = None
    a_hid_id: int | None = None
    try:
        hq = client.post(
            "/api/v1/departments",
            headers=_headers(admin_token),
            json={"name": "测试集团", "code": f"T{u}_hq", "parent_id": None},
        ).json()["data"]
        sec = client.post(
            "/api/v1/departments",
            headers=_headers(admin_token),
            json={"name": "测试段", "code": f"T{u}_sec", "parent_id": hq["id"]},
        ).json()["data"]
        # 用户归属 SEC，scope=3 → 可见 {SEC, WS×下级}，不可见 HQ
        role = _make_role(
            client,
            admin_token,
            u,
            f"T{u}_MON",
            3,
            ["project:list", "project:add", "alarm:handle"],
        )
        sec_token = _make_user(
            client,
            admin_token,
            u,
            f"T{u}_mon",
            role["code"],
            sec["id"],
        )
        # 项目：一个在 SEC（可见），一个在 HQ（不可见）
        p_sec = client.post(
            "/api/v1/projects",
            headers=_headers(admin_token),
            json={"name": f"P{u}_sec", "dept_id": sec["id"], "status": "在建"},
        ).json()["data"]
        p_hq = client.post(
            "/api/v1/projects",
            headers=_headers(admin_token),
            json={"name": f"P{u}_hq", "dept_id": hq["id"], "status": "在建"},
        ).json()["data"]
        p_sec_id, p_hq_id = p_sec["id"], p_hq["id"]
        a_vis = AlarmModel(
            project_id=p_sec_id,
            alarm_type="fence_intrusion",
            device_type="anti_intrusion",
            device_no=f"T{u}_D1",
            alarm_level="严重",
            handle_status="待处理",
            alarm_time=datetime(2026, 7, 17, 10, 0, 0),
            alarm_info="visible",
        )
        a_hid = AlarmModel(
            project_id=p_hq_id,
            alarm_type="device_alarm",
            device_type="locate",
            device_no=f"T{u}_D2",
            alarm_level="提示",
            handle_status="待处理",
            alarm_time=datetime(2026, 7, 17, 11, 0, 0),
            alarm_info="hidden",
        )
        db.add_all([a_vis, a_hid])
        db.commit()
        db.refresh(a_vis)
        db.refresh(a_hid)
        a_vis_id, a_hid_id = a_vis.id, a_hid.id
        assert a_vis_id is not None and a_hid_id is not None

        # 可见告警可处置 → 200
        r = client.post(
            f"/api/v1/alarms/{a_vis.id}/handle",
            headers=_headers(sec_token),
            json={"handle_status": "已处理", "content": "已核实"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["handle_status"] == "已处理"

        # 不可见告警 → 404（不暴露越权）
        r = client.post(
            f"/api/v1/alarms/{a_hid.id}/handle",
            headers=_headers(sec_token),
            json={"handle_status": "已处理", "content": ""},
        )
        assert r.status_code == 404, r.text
    finally:
        db.close()
        db = SessionLocal()
        try:
            if a_vis_id is not None:
                db.execute(delete(AlarmModel).where(AlarmModel.id == a_vis_id))
            if a_hid_id is not None:
                db.execute(delete(AlarmModel).where(AlarmModel.id == a_hid_id))
            if p_sec_id is not None:
                db.execute(delete(Project).where(Project.id == p_sec_id))
            if p_hq_id is not None:
                db.execute(delete(Project).where(Project.id == p_hq_id))
            db.commit()
        finally:
            db.close()
        _cleanup(u)

"""作业计划管理 · 作业列表（原型三步向导）测试。

覆盖：
- 结构化绑定往返：人员↔定位设备、大机六要素、围栏逐条规则的写入与详情回显；
- 行内设备自动并入 ``work_plan_device``（规则引擎 v2 的设备覆盖）；
- 计划级 ``rule_json`` 由首条围栏规则派生（引擎判定不回归）；
- 更新为「全量重链」语义（少给即删）；
- 旧版 ``*_ids`` 简写仍兼容；
- 列表排序白名单：sort_by/order 生效，非法字段回落创建时间倒序。

以真实库通过 TestClient 运行；按 uid 前缀清理自建数据。
"""

import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.main import app
from app.model.device import AntiIntrusionDevice, LocateDevice, TrainApproachDevice
from app.model.fence import ElectronicFence
from app.model.job import WorkPlan, WorkPlanDevice, WorkPlanFence
from app.model.person import Machine, Person
from app.model.project import Project
from app.model.system import Department


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
        plan_ids = db.scalars(select(WorkPlan.id).where(WorkPlan.name.like(f"J{u}%"))).all()
        if plan_ids:
            db.execute(delete(WorkPlanDevice).where(WorkPlanDevice.plan_id.in_(plan_ids)))
            db.execute(delete(WorkPlanFence).where(WorkPlanFence.plan_id.in_(plan_ids)))
        db.execute(delete(WorkPlan).where(WorkPlan.name.like(f"J{u}%")))
        for model in (LocateDevice, AntiIntrusionDevice, TrainApproachDevice):
            db.execute(delete(model).where(model.device_no.like(f"{u}%")))
        db.execute(delete(Machine).where(Machine.machine_no.like(f"M{u}%")))
        db.execute(delete(Person).where(Person.name.like(f"P{u}%")))
        db.execute(delete(ElectronicFence).where(ElectronicFence.name.like(f"F{u}%")))
        db.execute(delete(Project).where(Project.name.like(f"P{u}%")))
        db.execute(delete(Department).where(Department.code.like(f"T{u}%")))
        db.commit()
    finally:
        db.close()


def _bootstrap(client, admin_token, u) -> dict:
    """建部门/项目/人员×2/大机/围栏/设备×3，返回 id 字典。"""
    dept = client.post(
        "/api/v1/departments",
        headers=_headers(admin_token),
        json={"name": f"部门{u}", "code": f"T{u}_A", "parent_id": None},
    ).json()["data"]
    proj = client.post(
        "/api/v1/projects",
        headers=_headers(admin_token),
        json={"name": f"P{u}_项目", "dept_id": dept["id"], "status": "在建"},
    ).json()["data"]

    def _person(suffix: str) -> dict:
        return client.post(
            "/api/v1/persons",
            headers=_headers(admin_token),
            json={
                "project_id": proj["id"],
                "person_no": f"PN{u}{suffix}",
                "name": f"P{u}_{suffix}",
            },
        ).json()["data"]

    def _device(dtype: str, suffix: str) -> dict:
        return client.post(
            "/api/v1/devices",
            headers=_headers(admin_token),
            json={
                "device_type": dtype,
                "project_id": proj["id"],
                "name": f"D{u}_{suffix}",
                "device_no": f"{u}{suffix}",
            },
        ).json()["data"]

    machine = client.post(
        "/api/v1/machines",
        headers=_headers(admin_token),
        json={"project_id": proj["id"], "machine_no": f"M{u}", "machine_type": "捣固车"},
    ).json()["data"]
    fence = client.post(
        "/api/v1/fences",
        headers=_headers(admin_token),
        json={"project_id": proj["id"], "name": f"F{u}_围栏"},
    ).json()["data"]

    return {
        "dept": dept,
        "project": proj,
        "guard": _person("G"),
        "driver": _person("D"),
        "locate": _device("locate", "L1"),
        "arm": _device("anti_intrusion", "A1"),
        "voice": _device("train_approach", "V1"),
        "machine": machine,
        "fence": fence,
    }


def test_structured_bindings_roundtrip(client, admin_token):
    """三步向导提交的行式绑定应完整落库并回显（含名称）。"""
    u = _uid()
    try:
        env = _bootstrap(client, admin_token, u)
        r = client.post(
            "/api/v1/jobs",
            headers=_headers(admin_token),
            json={
                "project_id": env["project"]["id"],
                "name": f"J{u}_向导",
                "is_start": True,
                "description": "K120+300 至 K120+800",
                "plan_time": "2026-08-05 22:00:00~2026-08-06 04:00:00",
                "status": "执行中",
                "person_bindings": [
                    {"person_id": env["guard"]["id"], "device_no": env["locate"]["device_no"]}
                ],
                "machine_bindings": [
                    {
                        "machine_id": env["machine"]["id"],
                        "guard_person_id": env["guard"]["id"],
                        "driver_person_id": env["driver"]["id"],
                        "arm_device_no": env["arm"]["device_no"],
                        "voice_device_no": env["voice"]["device_no"],
                    }
                ],
                "fence_rules": [
                    {
                        "fence_id": env["fence"]["id"],
                        "monitor_target": "计划外人员",
                        "trigger_condition": "进入",
                        "time_range": "22:00:00~04:00:00",
                        "dwell_time": 5,
                    }
                ],
            },
        )
        assert r.status_code == 200, r.text
        jid = r.json()["data"]["id"]

        d = client.get(f"/api/v1/jobs/{jid}", headers=_headers(admin_token)).json()["data"]

        # 人员行：人员 + 定位设备成对回显
        assert len(d["person_bindings"]) == 1
        pb = d["person_bindings"][0]
        assert pb["person_id"] == env["guard"]["id"]
        assert pb["person_name"] == env["guard"]["name"]
        assert pb["person_no"] == env["guard"]["person_no"]
        assert pb["device_no"] == env["locate"]["device_no"]
        assert pb["device_name"] == env["locate"]["name"]

        # 大机行：六要素回显
        mb = d["machine_bindings"][0]
        assert mb["machine_no"] == f"M{u}"
        assert mb["guard_person_name"] == env["guard"]["name"]
        assert mb["driver_person_name"] == env["driver"]["name"]
        assert mb["arm_device_no"] == env["arm"]["device_no"]
        assert mb["arm_device_name"] == env["arm"]["name"]
        assert mb["body_device_no"] is None
        assert mb["voice_device_name"] == env["voice"]["name"]

        # 围栏行：逐条规则回显
        fr = d["fence_rules"][0]
        assert fr["fence_id"] == env["fence"]["id"]
        assert fr["fence_name"] == f"F{u}_围栏"
        assert fr["monitor_target"] == "计划外人员"
        assert fr["trigger_condition"] == "进入"
        assert fr["time_range"] == "22:00:00~04:00:00"
        assert fr["dwell_time"] == 5

        # 行内设备自动并入设备覆盖（规则引擎 v2 依赖）
        covered = {(x["device_type"], x["device_no"]) for x in d["devices"]}
        assert ("locate", env["locate"]["device_no"]) in covered
        assert ("anti_intrusion", env["arm"]["device_no"]) in covered
        assert ("train_approach", env["voice"]["device_no"]) in covered

        # 计划级聚合规则由首条围栏规则派生
        assert d["rule"]["monitor_target"] == "计划外人员"
        assert d["rule"]["trigger_conditions"] == ["fence_intrusion"]
        assert d["rule"]["dwell_time"] == 5

        # 兼容旧字段：展开列表仍在
        assert [p["id"] for p in d["persons"]] == [env["guard"]["id"]]
        assert [m["id"] for m in d["machines"]] == [env["machine"]["id"]]
        assert [f["id"] for f in d["fences"]] == [env["fence"]["id"]]
    finally:
        _cleanup(u)


def test_update_replaces_bindings(client, admin_token):
    """编辑时给出结构化绑定 = 全量重链：少给的行会被删除。"""
    u = _uid()
    try:
        env = _bootstrap(client, admin_token, u)
        jid = client.post(
            "/api/v1/jobs",
            headers=_headers(admin_token),
            json={
                "project_id": env["project"]["id"],
                "name": f"J{u}_重链",
                "person_bindings": [
                    {"person_id": env["guard"]["id"], "device_no": env["locate"]["device_no"]},
                    {"person_id": env["driver"]["id"]},
                ],
                "fence_rules": [{"fence_id": env["fence"]["id"], "monitor_target": "计划内人员"}],
            },
        ).json()["data"]["id"]

        r = client.put(
            f"/api/v1/jobs/{jid}",
            headers=_headers(admin_token),
            json={
                "person_bindings": [{"person_id": env["driver"]["id"], "device_no": None}],
                "machine_bindings": [],
                "fence_rules": [
                    {
                        "fence_id": env["fence"]["id"],
                        "monitor_target": "计划外大机",
                        "trigger_condition": "离开",
                        "dwell_time": 30,
                    }
                ],
            },
        )
        assert r.status_code == 200, r.text

        d = client.get(f"/api/v1/jobs/{jid}", headers=_headers(admin_token)).json()["data"]
        assert [b["person_id"] for b in d["person_bindings"]] == [env["driver"]["id"]]
        assert d["machine_bindings"] == []
        assert d["fence_rules"][0]["monitor_target"] == "计划外大机"
        assert d["fence_rules"][0]["trigger_condition"] == "离开"
        assert d["fence_rules"][0]["dwell_time"] == 30
        # 派生规则同步刷新
        assert d["rule"]["monitor_target"] == "计划外大机"
    finally:
        _cleanup(u)


def test_legacy_ids_still_supported(client, admin_token):
    """未升级的调用方仍可用 person_ids / fence_ids 简写。"""
    u = _uid()
    try:
        env = _bootstrap(client, admin_token, u)
        jid = client.post(
            "/api/v1/jobs",
            headers=_headers(admin_token),
            json={
                "project_id": env["project"]["id"],
                "name": f"J{u}_旧版",
                "person_ids": [env["guard"]["id"]],
                "machine_ids": [env["machine"]["id"]],
                "fence_ids": [env["fence"]["id"]],
            },
        ).json()["data"]["id"]

        d = client.get(f"/api/v1/jobs/{jid}", headers=_headers(admin_token)).json()["data"]
        assert [b["person_id"] for b in d["person_bindings"]] == [env["guard"]["id"]]
        assert d["person_bindings"][0]["device_no"] is None
        assert [b["machine_id"] for b in d["machine_bindings"]] == [env["machine"]["id"]]
        assert [f["fence_id"] for f in d["fence_rules"]] == [env["fence"]["id"]]
    finally:
        _cleanup(u)


def test_list_sorting_whitelist(client, admin_token):
    """列表排序：sort_by/order 生效；非法字段回落创建时间倒序。"""
    u = _uid()
    try:
        env = _bootstrap(client, admin_token, u)
        names = [f"J{u}_A", f"J{u}_B", f"J{u}_C"]
        for n in names:
            r = client.post(
                "/api/v1/jobs",
                headers=_headers(admin_token),
                json={"project_id": env["project"]["id"], "name": n},
            )
            assert r.status_code == 200, r.text

        def _names(**params) -> list[str]:
            r = client.get(
                "/api/v1/jobs",
                headers=_headers(admin_token),
                params={"keyword": f"J{u}_", "size": 50, **params},
            )
            assert r.status_code == 200, r.text
            return [it["name"] for it in r.json()["data"]["items"]]

        assert _names(sort_by="name", order="asc") == names
        assert _names(sort_by="name", order="desc") == list(reversed(names))
        # 默认 & 非法排序字段 → 创建时间倒序（最后创建的在最前）
        assert _names()[0] == names[-1]
        assert _names(sort_by="; drop table", order="desc")[0] == names[-1]
    finally:
        _cleanup(u)


def test_list_filters_by_is_start_and_status(client, admin_token):
    """原型查询条件：计划启动 + 计划状态。"""
    u = _uid()
    try:
        env = _bootstrap(client, admin_token, u)
        on = client.post(
            "/api/v1/jobs",
            headers=_headers(admin_token),
            json={
                "project_id": env["project"]["id"],
                "name": f"J{u}_启动",
                "is_start": True,
                "status": "执行中",
            },
        ).json()["data"]
        off = client.post(
            "/api/v1/jobs",
            headers=_headers(admin_token),
            json={
                "project_id": env["project"]["id"],
                "name": f"J{u}_关闭",
                "is_start": False,
                "status": "草稿",
            },
        ).json()["data"]

        r = client.get(
            "/api/v1/jobs",
            headers=_headers(admin_token),
            params={"keyword": f"J{u}_", "is_start": True, "size": 50},
        )
        ids = {it["id"] for it in r.json()["data"]["items"]}
        assert on["id"] in ids and off["id"] not in ids

        r = client.get(
            "/api/v1/jobs",
            headers=_headers(admin_token),
            params={"keyword": f"J{u}_", "status": "草稿", "size": 50},
        )
        ids = {it["id"] for it in r.json()["data"]["items"]}
        assert off["id"] in ids and on["id"] not in ids
    finally:
        _cleanup(u)

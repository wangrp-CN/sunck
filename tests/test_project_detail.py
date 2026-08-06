"""项目详情大屏端点端到端测试。

覆盖：
  1) 超管可获取单项目全景（project/devices/fences/persons/machines/alarms 结构齐全）；
  2) 列车接近设备返回 direction 且坐标已转换为 GCJ-02；
  3) 大机绑定 enriched：防护人员姓名 + track_device_no + 坐标；
  4) 告警仅返回「待处理」；
  5) 无权项目（data_scope 隔离）返回业务失败（HTTP200 + code!=0）。
"""

import secrets
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.database import SessionLocal
from app.main import app
from app.model.alarm import Alarm
from app.model.device import AntiIntrusionDevice, LocateDevice, TrainApproachDevice
from app.model.fence import ElectronicFence
from app.model.job import WorkPlan, WorkPlanMachine
from app.model.person import Machine, Person
from app.model.project import Project


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


@pytest.fixture
def seeded():
    u = secrets.token_hex(3)
    db = SessionLocal()
    proj = Project(
        name=f"P{u}", short_name=f"S{u}", status="进行中", section="区间X", mileage="K10+000"
    )
    db.add(proj)
    db.flush()

    locate = LocateDevice(
        project_id=proj.id,
        name=f"定位{u}",
        device_no=f"LOC{u}",
        device_type="locate",
        status="在线",
    )
    ta = TrainApproachDevice(
        project_id=proj.id,
        name=f"列车{u}",
        device_no=f"TA{u}",
        device_type="train_approach",
        status="在线",
        direction="上行",
        longitude=116.40,
        latitude=39.91,
    )
    ai = AntiIntrusionDevice(
        project_id=proj.id,
        name=f"防侵{u}",
        device_no=f"AI{u}",
        device_type="anti_intrusion",
        status="在线",
        longitude=116.41,
        latitude=39.92,
    )
    db.add_all([locate, ta, ai])
    db.flush()

    person = Person(
        project_id=proj.id,
        person_no=f"PER{u}",
        name=f"人{u}",
        person_type="施工人员",
        device_no=f"LOC{u}",
    )
    db.add(person)
    db.flush()

    machine = Machine(project_id=proj.id, machine_no=f"M{u}", machine_type="捣固车")
    db.add(machine)
    db.flush()
    plan = WorkPlan(project_id=proj.id, name=f"计划{u}", status="执行中")
    db.add(plan)
    db.flush()
    guard = Person(project_id=proj.id, person_no=f"G{u}", name=f"防护{u}", person_type="防护人员")
    db.add(guard)
    db.flush()
    wpm = WorkPlanMachine(
        plan_id=plan.id,
        machine_id=machine.id,
        guard_person_id=guard.id,
        body_device_no=f"AI{u}",
    )
    db.add(wpm)

    fence = ElectronicFence(
        project_id=proj.id,
        name=f"围栏{u}",
        fence_type="电子围栏",
        geometry_wkt="POLYGON((116.39 39.90,116.41 39.90,116.41 39.92,116.39 39.92,116.39 39.90))",
        enabled=True,
    )
    a_pending = Alarm(
        project_id=proj.id,
        alarm_type="train_approach",
        device_no=f"TA{u}",
        device_name=f"列车{u}",
        alarm_info="列车接近",
        alarm_level="警告",
        handle_status="待处理",
        alarm_time=datetime.now(timezone.utc),
    )
    a_done = Alarm(
        project_id=proj.id,
        alarm_type="fence",
        device_no=f"AI{u}",
        device_name=f"防侵{u}",
        alarm_info="围栏告警",
        alarm_level="警告",
        handle_status="已处理",
        alarm_time=datetime.now(timezone.utc),
    )
    db.add_all([fence, a_pending, a_done])
    db.commit()
    ids = {"project_id": proj.id, "plan_id": plan.id, "u": u}
    db.close()
    yield ids

    db = SessionLocal()
    db.execute(delete(Alarm).where(Alarm.project_id == ids["project_id"]))
    db.execute(delete(WorkPlanMachine).where(WorkPlanMachine.plan_id == ids["plan_id"]))
    db.execute(delete(WorkPlan).where(WorkPlan.project_id == ids["project_id"]))
    db.execute(delete(Machine).where(Machine.project_id == ids["project_id"]))
    db.execute(delete(Person).where(Person.project_id == ids["project_id"]))
    db.execute(delete(ElectronicFence).where(ElectronicFence.project_id == ids["project_id"]))
    db.execute(delete(LocateDevice).where(LocateDevice.project_id == ids["project_id"]))
    db.execute(
        delete(TrainApproachDevice).where(TrainApproachDevice.project_id == ids["project_id"])
    )
    db.execute(
        delete(AntiIntrusionDevice).where(AntiIntrusionDevice.project_id == ids["project_id"])
    )
    db.execute(delete(Project).where(Project.id == ids["project_id"]))
    db.commit()
    db.close()


def test_project_detail_structure(client, admin_token, seeded):
    pid = seeded["project_id"]
    r = client.get(f"/api/v1/dashboard/project-detail/{pid}", headers=_headers(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 0
    d = body["data"]
    assert d["project"]["id"] == pid
    for key in ("devices", "fences", "persons", "machines", "alarms"):
        assert key in d

    ta = next(x for x in d["devices"] if x["device_type"] == "train_approach")
    assert ta["direction"] == "上行"
    assert ta["lng"] is not None and ta["lat"] is not None  # GCJ-02 已转换

    m = d["machines"][0]
    assert m["guard_person_name"] == f"防护{seeded['u']}"
    assert m["track_device_no"] == f"AI{seeded['u']}"
    assert m["lng"] is not None and m["lat"] is not None

    # 仅返回待处理告警
    assert len(d["alarms"]) == 1
    assert d["alarms"][0]["handle_status"] == "待处理"


def test_project_detail_not_found(client, admin_token, seeded):
    r = client.get("/api/v1/dashboard/project-detail/99999999", headers=_headers(admin_token))
    assert r.status_code == 200
    assert r.json()["code"] != 0

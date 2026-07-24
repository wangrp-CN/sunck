"""P3 业务模块集成测试：数据字典/巡检/视频/计划模板/设备健康/对比大屏。

复用 conftest 的 client / admin_token（真实 dev DB）；清理按 id（级联/硬删）。
聚焦业务正确性（状态机、克隆、AI 回推、聚合口径）。
"""

import uuid

import pytest

from app.core.database import SessionLocal
from app.model.dict import DictType
from app.model.hazard import Hazard
from app.model.inspection import InspectionTask
from app.model.job import WorkPlan
from app.model.video import VideoChannel

API_DICT = "/api/v1/dicts"
API_INSPECT = "/api/v1/inspections"
API_VIDEO = "/api/v1/videos"
API_JOB = "/api/v1/jobs"
API_DEVICE = "/api/v1/devices"
API_DASH = "/api/v1/dashboard"

_CREATED: dict[str, list] = {
    "dict": [],
    "inspect_task": [],
    "video": [],
    "job": [],
    "hazard": [],
}


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    db = SessionLocal()
    if _CREATED["hazard"]:
        db.query(Hazard).filter(Hazard.id.in_(_CREATED["hazard"])).delete(synchronize_session=False)
    if _CREATED["inspect_task"]:
        db.query(InspectionTask).filter(InspectionTask.id.in_(_CREATED["inspect_task"])).delete(
            synchronize_session=False
        )
    if _CREATED["video"]:
        db.query(VideoChannel).filter(VideoChannel.id.in_(_CREATED["video"])).delete(
            synchronize_session=False
        )
    if _CREATED["job"]:
        db.query(WorkPlan).filter(WorkPlan.id.in_(_CREATED["job"])).delete(
            synchronize_session=False
        )
    if _CREATED["dict"]:
        db.query(DictType).filter(DictType.code.in_(_CREATED["dict"])).delete(
            synchronize_session=False
        )
    db.commit()
    db.close()
    for v in _CREATED.values():
        v.clear()


def _u(p):
    return f"{p}-{uuid.uuid4().hex[:8]}"


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


# ---------------- 巡检 ----------------
def test_inspection_lifecycle(client, admin_token):
    r = client.post(
        f"{API_INSPECT}",
        json={"name": _u("巡检任务"), "project_id": None, "required_checkins": 2},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    tid = r.json()["data"]["id"]
    _CREATED["inspect_task"].append(tid)
    assert r.json()["data"]["status"] == "待巡检"

    # start → 巡检中
    r = client.post(
        f"{API_INSPECT}/{tid}/transition",
        json={"action": "start"},
        headers=_auth(admin_token),
    )
    assert r.json()["data"]["status"] == "巡检中"

    # 打卡（异常）→ 自动置巡检中
    r = client.post(
        f"{API_INSPECT}/{tid}/checkin",
        json={"result": "异常", "note": "发现杂物", "checkin_by_name": "张三"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    rec_id = r.json()["data"]["id"]

    # 异常打卡转隐患
    r = client.post(
        f"{API_INSPECT}/records/{rec_id}/convert-to-hazard",
        headers=_auth(admin_token),
    )
    assert r.json()["code"] == 0
    hid = r.json()["data"]["hazard_id"]
    _CREATED["hazard"].append(hid)

    # finish → 已完成
    r = client.post(
        f"{API_INSPECT}/{tid}/transition",
        json={"action": "finish"},
        headers=_auth(admin_token),
    )
    assert r.json()["data"]["status"] == "已完成"
    assert r.json()["data"]["checkin_count"] == 1
    assert r.json()["data"]["abnormal_count"] == 1


def test_inspection_invalid_transition(client, admin_token):
    r = client.post(f"{API_INSPECT}", json={"name": _u("巡检")}, headers=_auth(admin_token))
    tid = r.json()["data"]["id"]
    _CREATED["inspect_task"].append(tid)
    # 待巡检直接 finish → 业务 400
    r = client.post(
        f"{API_INSPECT}/{tid}/transition",
        json={"action": "finish"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200 and r.json()["code"] == 400


# ---------------- 视频 AI ----------------
def test_video_channel_and_event_ingest(client, admin_token):
    no = _u("CH")
    r = client.post(
        f"{API_VIDEO}/channels",
        json={"name": _u("通道"), "channel_no": no, "ai_enabled": True},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    cid = r.json()["data"]["id"]
    _CREATED["video"].append(cid)

    # 外部回推 AI 事件
    r = client.post(
        f"{API_VIDEO}/events/ingest",
        json={"channel_no": no, "event_type": "intrusion", "confidence": 0.91},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["event_type"] == "intrusion"
    eid = r.json()["data"]["id"]

    # 事件列表可见
    r = client.get(f"{API_VIDEO}/events", headers=_auth(admin_token))
    assert any(e["id"] == eid for e in r.json()["data"]["items"])

    # 标记已处理
    r = client.post(f"{API_VIDEO}/events/{eid}/handle", headers=_auth(admin_token))
    assert r.json()["data"]["handled"] is True


def test_video_ingest_unknown_channel(client, admin_token):
    r = client.post(
        f"{API_VIDEO}/events/ingest",
        json={"channel_no": "NO_SUCH", "event_type": "intrusion"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200 and r.json()["code"] == 404


# ---------------- 计划模板/克隆 ----------------
def test_job_clone_and_template(client, admin_token):
    r = client.post(
        f"{API_JOB}",
        json={"name": _u("作业计划"), "status": "草稿"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    jid = r.json()["data"]["id"]
    _CREATED["job"].append(jid)

    # 克隆 → 新草稿
    r = client.post(f"{API_JOB}/{jid}/clone", headers=_auth(admin_token))
    assert r.json()["code"] == 0
    clone_id = r.json()["data"]["id"]
    _CREATED["job"].append(clone_id)
    assert r.json()["data"]["name"].endswith("(副本)")
    assert r.json()["data"]["status"] == "草稿"
    assert r.json()["data"]["is_template"] is False

    # 存为模板
    r = client.post(f"{API_JOB}/{jid}/save-as-template", headers=_auth(admin_token))
    assert r.json()["code"] == 0
    tmpl_id = r.json()["data"]["id"]
    _CREATED["job"].append(tmpl_id)
    assert r.json()["data"]["is_template"] is True

    # 列表默认(非模板)不应包含模板
    r = client.get(f"{API_JOB}", headers=_auth(admin_token))
    ids = [i["id"] for i in r.json()["data"]["items"]]
    assert tmpl_id not in ids
    # 模板库视图仅含模板
    r = client.get(f"{API_JOB}", params={"is_template": True}, headers=_auth(admin_token))
    ids = [i["id"] for i in r.json()["data"]["items"]]
    assert tmpl_id in ids


# ---------------- 设备健康 / 对比大屏 ----------------
def test_device_health(client, admin_token):
    r = client.get(f"{API_DEVICE}/health", params={"hours": 24}, headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    assert "total" in r.json()["data"]
    assert "online" in r.json()["data"]


def test_project_compare(client, admin_token):
    r = client.get(f"{API_DASH}/project-compare", params={"days": 7}, headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    assert "items" in r.json()["data"]

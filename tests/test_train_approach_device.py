"""列车接近报警设备 CRUD 与权限/数据隔离测试。

覆盖：
- 管理员完整增删改查（创建回填 project_name、按编号/状态过滤、软删后详情 404）。
- 设备编号唯一性：重复编号创建被 BusinessError 拦截（HTTP200 + code!=0）。
- 批量删除返回 deleted/total/skipped。
- 无 train_approach_device:add 权限用户创建被 403 拦截。

按 uid 前缀清理自建数据，避免污染开发库。
"""

from sqlalchemy import delete

from app.core.database import SessionLocal
from app.model.device import TrainApproachDevice
from app.model.project import Project
from tests.helpers import (
    _cleanup_org,
    _headers,
    _make_dept,
    _make_role,
    _make_user,
    _uid,
)

BASE = "/api/v1/train-approach-devices"


def _cleanup(u: str) -> None:
    db = SessionLocal()
    try:
        db.execute(delete(TrainApproachDevice).where(TrainApproachDevice.name.like(f"TA{u}%")))
        db.execute(delete(Project).where(Project.name.like(f"P{u}%")))
        db.commit()
    finally:
        db.close()
    _cleanup_org(u)


def _create_project(client, admin_token, u, dept_id, suffix):
    return client.post(
        "/api/v1/projects",
        headers=_headers(admin_token),
        json={"name": f"P{u}_{suffix}", "dept_id": dept_id},
    ).json()["data"]


def test_train_approach_device_full_crud_by_admin(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")
        # 1) 创建
        r = client.post(
            BASE,
            headers=_headers(admin_token),
            json={
                "project_id": proj["id"],
                "name": f"TA{u}_设备",
                "device_no": f"TA{u}001",
                "sn": f"SN{u}",
                "direction": "上行",
                "longitude": 116.397,
                "latitude": 39.909,
                "status": "在线",
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        did = data["id"]
        assert data["project_name"] == proj["name"]
        assert data["direction"] == "上行"
        assert data["longitude"] == 116.397

        # 2) 列表 + 名称模糊
        r = client.get(
            BASE,
            headers=_headers(admin_token),
            params={"name": f"TA{u}", "page": 1, "size": 20},
        )
        assert r.status_code == 200, r.text
        assert did in {it["id"] for it in r.json()["data"]["items"]}

        # 2b) 按设备编号精确过滤
        r = client.get(BASE, headers=_headers(admin_token), params={"device_no": f"TA{u}001"})
        assert r.status_code == 200, r.text
        assert [it["id"] for it in r.json()["data"]["items"]] == [did]

        # 2c) 按设备状态精确过滤
        r = client.get(
            BASE,
            headers=_headers(admin_token),
            params={"name": f"TA{u}", "status": "低电量"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["total"] == 0

        # 3) 详情
        r = client.get(f"{BASE}/{did}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        assert r.json()["data"]["id"] == did

        # 4) 更新
        r = client.put(
            f"{BASE}/{did}",
            headers=_headers(admin_token),
            json={"name": f"TA{u}_改", "status": "低电量", "direction": "下行"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["name"] == f"TA{u}_改"
        assert r.json()["data"]["status"] == "低电量"
        assert r.json()["data"]["direction"] == "下行"

        # 5) 删除（软删）-> 详情 404
        r = client.delete(f"{BASE}/{did}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        r = client.get(f"{BASE}/{did}", headers=_headers(admin_token))
        assert r.status_code == 404, r.text
    finally:
        _cleanup(u)


def test_train_approach_device_duplicate_device_no_rejected(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")
        no = f"TA{u}DUP"
        r = client.post(
            BASE,
            headers=_headers(admin_token),
            json={
                "project_id": proj["id"],
                "name": f"TA{u}_a",
                "device_no": no,
                "direction": "上行",
            },
        )
        assert r.status_code == 200, r.text
        # 重复设备编号 -> BusinessError（HTTP200 + code!=0）
        r = client.post(
            BASE,
            headers=_headers(admin_token),
            json={
                "project_id": proj["id"],
                "name": f"TA{u}_b",
                "device_no": no,
                "direction": "下行",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["code"] != 0
    finally:
        _cleanup(u)


def test_train_approach_device_batch_delete(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")
        ids = []
        for i in range(2):
            r = client.post(
                BASE,
                headers=_headers(admin_token),
                json={
                    "project_id": proj["id"],
                    "name": f"TA{u}_b{i}",
                    "device_no": f"TA{u}B{i}",
                    "direction": "上行",
                },
            )
            assert r.status_code == 200, r.text
            ids.append(r.json()["data"]["id"])

        r = client.post(f"{BASE}/batch-delete", headers=_headers(admin_token), json={"ids": ids})
        assert r.status_code == 200, r.text
        assert r.json()["data"]["deleted"] == 2
        assert r.json()["data"]["total"] == 2
        for did in ids:
            assert client.get(f"{BASE}/{did}", headers=_headers(admin_token)).status_code == 404
    finally:
        _cleanup(u)


def test_train_approach_device_direction_required_and_validated(client, admin_token):
    """设备方位必填且只能为「上行」/「下行」；空值或其它值均被拦截。"""
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")

        # 1) 缺失 direction -> 校验失败（HTTP200 + code!=0）
        r = client.post(
            BASE,
            headers=_headers(admin_token),
            json={
                "project_id": proj["id"],
                "name": f"TA{u}_nodir",
                "device_no": f"TA{u}NODIR",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["code"] != 0

        # 2) 非法 direction 值 -> 校验失败
        r = client.post(
            BASE,
            headers=_headers(admin_token),
            json={
                "project_id": proj["id"],
                "name": f"TA{u}_baddir",
                "device_no": f"TA{u}BADDIR",
                "direction": "北向",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["code"] != 0

        # 3) 合法 direction -> 创建成功
        r = client.post(
            BASE,
            headers=_headers(admin_token),
            json={
                "project_id": proj["id"],
                "name": f"TA{u}_ok",
                "device_no": f"TA{u}OK",
                "direction": "下行",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["direction"] == "下行"
    finally:
        _cleanup(u)


def test_train_approach_device_forbidden_without_permission(client, admin_token):
    """无 train_approach_device:add 权限的用户创建被 403 拦截。"""
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")
        role = _make_role(client, admin_token, u, "guest", ["dashboard:view"])
        token = _make_user(client, admin_token, u, f"T{u}user", role["code"], dept["id"])
        r = client.post(
            BASE,
            headers=_headers(token),
            json={
                "project_id": proj["id"],
                "name": f"TA{u}_x",
                "device_no": f"TA{u}X1",
                "direction": "上行",
            },
        )
        assert r.status_code == 403, r.text
    finally:
        _cleanup(u)

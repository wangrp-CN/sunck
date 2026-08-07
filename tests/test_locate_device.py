"""人机定位设备 CRUD 与权限/数据隔离测试。

覆盖：
- 管理员完整增删改查（创建回填 project_name、按设备类型过滤、软删后详情 404）。
- 设备编号唯一性：重复编号创建被 BusinessError 拦截（HTTP200 + code!=0）。
- 无 locate_device:add 权限用户创建被 403 拦截。

按 uid 前缀清理自建数据，避免污染开发库。
"""

from sqlalchemy import delete

from app.core.database import SessionLocal
from app.model.device import LocateDevice
from app.model.project import Project
from tests.helpers import (
    _cleanup_org,
    _headers,
    _make_dept,
    _make_role,
    _make_user,
    _uid,
)


def _cleanup(u: str) -> None:
    db = SessionLocal()
    try:
        db.execute(delete(LocateDevice).where(LocateDevice.name.like(f"LD{u}%")))
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


def test_locate_device_full_crud_by_admin(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")
        # 1) 创建
        r = client.post(
            "/api/v1/locate-devices",
            headers=_headers(admin_token),
            json={
                "project_id": proj["id"],
                "name": f"LD{u}_设备",
                "device_no": f"LD{u}001",
                "device_type": "大机机械定位设备",
                "status": "在线",
            },
        )
        assert r.status_code == 200, r.text
        did = r.json()["data"]["id"]
        assert r.json()["data"]["project_name"] == proj["name"]

        # 2) 列表 + 名称模糊
        r = client.get(
            "/api/v1/locate-devices",
            headers=_headers(admin_token),
            params={"name": f"LD{u}", "page": 1, "size": 20},
        )
        assert r.status_code == 200, r.text
        ids = {it["id"] for it in r.json()["data"]["items"]}
        assert did in ids

        # 2b) 按设备类型精确过滤
        r = client.get(
            "/api/v1/locate-devices",
            headers=_headers(admin_token),
            params={"device_type": "大机机械定位设备"},
        )
        assert r.status_code == 200, r.text
        assert all(it["device_type"] == "大机机械定位设备" for it in r.json()["data"]["items"])

        # 3) 详情
        r = client.get(f"/api/v1/locate-devices/{did}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        assert r.json()["data"]["id"] == did

        # 4) 更新
        r = client.put(
            f"/api/v1/locate-devices/{did}",
            headers=_headers(admin_token),
            json={"name": f"LD{u}_改", "status": "低电量"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["name"] == f"LD{u}_改"
        assert r.json()["data"]["status"] == "低电量"

        # 5) 删除（软删）-> 详情 404
        r = client.delete(f"/api/v1/locate-devices/{did}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        r = client.get(f"/api/v1/locate-devices/{did}", headers=_headers(admin_token))
        assert r.status_code == 404, r.text
    finally:
        _cleanup(u)


def test_locate_device_duplicate_device_no_rejected(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")
        no = f"LD{u}DUPU"
        r = client.post(
            "/api/v1/locate-devices",
            headers=_headers(admin_token),
            json={
                "project_id": proj["id"],
                "name": f"LD{u}_a",
                "device_no": no,
                "device_type": "人员手持机定位设备",
            },
        )
        assert r.status_code == 200, r.text
        # 重复设备编号 -> BusinessError（HTTP200 + code!=0）
        r = client.post(
            "/api/v1/locate-devices",
            headers=_headers(admin_token),
            json={
                "project_id": proj["id"],
                "name": f"LD{u}_b",
                "device_no": no,
                "device_type": "人员手持机定位设备",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["code"] != 0
    finally:
        _cleanup(u)


def test_locate_device_forbidden_without_permission(client, admin_token):
    """无 locate_device:add 权限的用户创建被 403 拦截。"""
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")
        role = _make_role(client, admin_token, u, "guest", ["dashboard:view"])
        token = _make_user(client, admin_token, u, f"T{u}user", role["code"], dept["id"])
        r = client.post(
            "/api/v1/locate-devices",
            headers=_headers(token),
            json={
                "project_id": proj["id"],
                "name": f"LD{u}_x",
                "device_no": f"LD{u}X1",
                "device_type": "人员手持机定位设备",
            },
        )
        assert r.status_code == 403, r.text
    finally:
        _cleanup(u)

"""地图资源库集成测试：CRUD、名称去重、类型过滤、软删、权限。

复用 conftest 的 client / admin_token（真实 dev DB）；清理按 id 硬删。
"""

import uuid

import pytest

from app.core.database import SessionLocal
from app.model.map_asset import MapAsset

API = "/api/v1/maps"

_CREATED_IDS: list[int] = []


@pytest.fixture(autouse=True)
def _cleanup_maps():
    yield
    if _CREATED_IDS:
        db = SessionLocal()
        db.query(MapAsset).filter(MapAsset.id.in_(_CREATED_IDS)).delete(synchronize_session=False)
        db.commit()
        db.close()
        _CREATED_IDS.clear()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _name() -> str:
    return f"测试资源_{uuid.uuid4().hex[:8]}"


def _create(client, token, **over):
    body = {
        "name": over.get("name", _name()),
        "type": over.get("type", "station_plan"),
        "project_id": over.get("project_id"),
        "center_lng": over.get("center_lng", 116.397),
        "center_lat": over.get("center_lat", 39.908),
        "zoom": over.get("zoom", 12),
        "coverage_wkt": over.get("coverage_wkt"),
        "image_url": over.get("image_url"),
        "remark": over.get("remark", "自动化测试"),
        "operator": over.get("operator", "tester"),
    }
    r = client.post(API, json=body, headers=_auth(token))
    assert r.status_code == 200, r.text
    resp = r.json()
    assert resp["code"] == 0, resp
    _CREATED_IDS.append(resp["data"]["id"])
    return resp["data"]


def test_map_asset_crud(client, admin_token):
    data = _create(client, admin_token)
    aid = data["id"]
    assert data["type"] == "station_plan"
    assert data["operator"] == "tester"

    # 列表可见
    r = client.get(API, params={"keyword": data["name"]}, headers=_auth(admin_token))
    assert r.status_code == 200
    assert any(t["id"] == aid for t in r.json()["data"]["items"])

    # 类型过滤
    r = client.get(API, params={"asset_type": "satellite"}, headers=_auth(admin_token))
    assert r.status_code == 200
    assert all(t["type"] == "satellite" for t in r.json()["data"]["items"])

    # 更新
    r = client.put(
        f"{API}/{aid}",
        json={"name": "改名资源", "zoom": 15},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "改名资源"
    assert r.json()["data"]["zoom"] == 15

    # 删除（软删）
    r = client.delete(f"{API}/{aid}", headers=_auth(admin_token))
    assert r.status_code == 200
    assert r.json()["code"] == 0
    r = client.get(f"{API}/{aid}", headers=_auth(admin_token))
    assert r.json()["code"] == 404


def test_map_asset_name_dedup(client, admin_token):
    data = _create(client, admin_token)
    name = data["name"]
    r = client.post(
        API,
        json={"name": name, "type": "plan_image"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    assert r.json()["code"] == 400


def test_map_asset_unauthorized(client):
    r = client.get(API)
    assert r.status_code == 401

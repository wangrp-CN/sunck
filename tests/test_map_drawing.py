"""地图手动绘制集成测试：点/线 CRUD、几何校验、名称去重、过滤、软删、权限。

复用 conftest 的 client / admin_token（真实 dev DB）；清理按 id 硬删。
"""

import uuid

import pytest

from app.core.database import SessionLocal
from app.model.map_drawing import MapDrawing
from app.service.map_drawing_service import haversine_m, polyline_length_m

API = "/api/v1/map-drawings"

_CREATED_IDS: list[int] = []


@pytest.fixture(autouse=True)
def _cleanup_drawings():
    yield
    if _CREATED_IDS:
        db = SessionLocal()
        db.query(MapDrawing).filter(MapDrawing.id.in_(_CREATED_IDS)).delete(
            synchronize_session=False
        )
        db.commit()
        db.close()
        _CREATED_IDS.clear()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _name(prefix: str = "测试标注") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _create(client, token, **over):
    body = {
        "name": over.get("name", _name()),
        "kind": over.get("kind", "point"),
        "mode": over.get("mode", "free"),
        "points": over.get("points", [[116.397, 39.908]]),
        "project_id": over.get("project_id"),
        "color": over.get("color", "#f56c6c"),
        "remark": over.get("remark", "自动化测试"),
    }
    if "operator" in over:
        body["operator"] = over["operator"]
    r = client.post(API, json=body, headers=_auth(token))
    assert r.status_code == 200, r.text
    resp = r.json()
    assert resp["code"] == 0, resp
    _CREATED_IDS.append(resp["data"]["id"])
    return resp["data"]


def test_geometry_helpers():
    """经纬度距离与折线长度计算合理。"""
    d = haversine_m(116.0, 39.9, 116.01, 39.9)
    assert 800 < d < 900  # 0.01 度经度在北纬 39.9 约 853m
    assert polyline_length_m([[116.0, 39.9]]) == 0.0
    two = polyline_length_m([[116.0, 39.9], [116.01, 39.9]])
    assert abs(two - round(d, 2)) < 0.1


def test_point_free_crud(client, admin_token):
    data = _create(client, admin_token)
    did = data["id"]
    assert data["kind"] == "point"
    assert data["mode"] == "free"
    assert data["points"] == [[116.397, 39.908]]
    assert data["center_lng"] == 116.397
    assert data["length_m"] is None
    # operator 未传时自动回填当前用户
    assert data["operator"]

    # 列表可见 + 类型过滤
    r = client.get(API, params={"keyword": data["name"]}, headers=_auth(admin_token))
    assert r.status_code == 200
    assert any(t["id"] == did for t in r.json()["data"]["items"])

    r = client.get(API, params={"kind": "line"}, headers=_auth(admin_token))
    assert all(t["kind"] == "line" for t in r.json()["data"]["items"])

    # 更新（改名 + 挪点）
    new_name = _name("改名点")
    r = client.put(
        f"{API}/{did}",
        json={"name": new_name, "points": [[116.5, 40.0]]},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    out = r.json()["data"]
    assert out["name"] == new_name
    assert out["points"] == [[116.5, 40.0]]
    assert out["center_lat"] == 40.0

    # 删除（软删）
    r = client.delete(f"{API}/{did}", headers=_auth(admin_token))
    assert r.json()["code"] == 0
    r = client.get(f"{API}/{did}", headers=_auth(admin_token))
    assert r.json()["code"] == 404


def test_point_coord_mode(client, admin_token):
    data = _create(client, admin_token, mode="coord", points=[[117.2, 39.13]])
    assert data["mode"] == "coord"
    assert data["points"] == [[117.2, 39.13]]


def test_line_free_and_road(client, admin_token):
    free = _create(
        client,
        admin_token,
        kind="line",
        mode="free",
        points=[[116.30, 39.90], [116.35, 39.92], [116.40, 39.95]],
    )
    assert free["kind"] == "line"
    assert len(free["points"]) == 3
    assert free["length_m"] and free["length_m"] > 0

    road = _create(
        client,
        admin_token,
        kind="line",
        mode="road",
        points=[[116.30, 39.90], [116.31, 39.90]],
    )
    assert road["mode"] == "road"

    r = client.get(API, params={"mode": "road"}, headers=_auth(admin_token))
    assert all(t["mode"] == "road" for t in r.json()["data"]["items"])


def test_geometry_validation(client, admin_token):
    # 点只能 1 个坐标
    r = client.post(
        API,
        json={
            "name": _name(),
            "kind": "point",
            "mode": "free",
            "points": [[116.0, 39.0], [117.0, 40.0]],
        },
        headers=_auth(admin_token),
    )
    assert r.json()["code"] == 400

    # 线至少 2 个坐标
    r = client.post(
        API,
        json={"name": _name(), "kind": "line", "mode": "free", "points": [[116.0, 39.0]]},
        headers=_auth(admin_token),
    )
    assert r.json()["code"] == 400

    # kind/mode 组合非法：点不支持沿路
    r = client.post(
        API,
        json={"name": _name(), "kind": "point", "mode": "road", "points": [[116.0, 39.0]]},
        headers=_auth(admin_token),
    )
    assert r.json()["code"] == 400

    # 坐标越界
    r = client.post(
        API,
        json={"name": _name(), "kind": "point", "mode": "coord", "points": [[999.0, 39.0]]},
        headers=_auth(admin_token),
    )
    assert r.json()["code"] == 400


def test_name_required_and_dedup(client, admin_token):
    r = client.post(
        API,
        json={"name": "  ", "kind": "point", "mode": "free", "points": [[116.0, 39.0]]},
        headers=_auth(admin_token),
    )
    assert r.json()["code"] == 400

    data = _create(client, admin_token)
    r = client.post(
        API,
        json={
            "name": data["name"],
            "kind": "point",
            "mode": "free",
            "points": [[116.1, 39.1]],
        },
        headers=_auth(admin_token),
    )
    assert r.json()["code"] == 400


def test_options_endpoint(client, admin_token):
    r = client.get(f"{API}/options", headers=_auth(admin_token))
    assert r.status_code == 200
    data = r.json()["data"]
    assert {k["value"] for k in data["kinds"]} == {"point", "line"}
    assert {m["value"] for m in data["modes"]} == {"free", "coord", "road"}
    assert data["kind_modes"]["line"] == ["free", "road"]


def test_map_drawing_unauthorized(client):
    r = client.get(API)
    assert r.status_code == 401

"""数据字典集成测试：类型/项 CRUD、系统内置只读保护、value 去重、下拉引用。

复用 conftest 的 client / admin_token（真实 dev DB）；清理按 code 前缀硬删。
"""

import uuid

import pytest

from app.core.database import SessionLocal
from app.model.dict import DictType

API = "/api/v1/dicts"

_CREATED_CODES: list[str] = []


@pytest.fixture(autouse=True)
def _cleanup_dicts():
    yield
    if _CREATED_CODES:
        db = SessionLocal()
        db.query(DictType).filter(DictType.code.in_(_CREATED_CODES)).delete(
            synchronize_session=False
        )
        db.commit()
        db.close()
        _CREATED_CODES.clear()


def _code() -> str:
    return f"test_dict_{uuid.uuid4().hex[:8]}"


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create_type(client, token, **over):
    code = over.get("code", _code())
    body = {
        "code": code,
        "name": over.get("name", "测试字典"),
        "description": over.get("description", "自动化测试"),
        "items": over.get(
            "items",
            [
                {"label": "选项A", "value": "a", "sort": 1},
                {"label": "选项B", "value": "b", "sort": 2, "enabled": False},
            ],
        ),
    }
    r = client.post(API, json=body, headers=_auth(token))
    assert r.status_code == 200, r.text
    resp = r.json()
    assert resp["code"] == 0, resp
    _CREATED_CODES.append(code)
    return resp["data"]


def test_dict_type_crud(client, admin_token):
    data = _create_type(client, admin_token)
    code = data["code"]
    assert len(data["items"]) == 2
    assert data["system"] is False

    # 列表可见
    r = client.get(API, params={"keyword": code}, headers=_auth(admin_token))
    assert r.status_code == 200
    assert any(t["code"] == code for t in r.json()["data"]["items"])

    # 重复 code → 业务 400
    r = client.post(
        API,
        json={"code": code, "name": "重复", "items": []},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    assert r.json()["code"] == 400

    # 更新名称
    r = client.put(f"{API}/{code}", json={"name": "新名称"}, headers=_auth(admin_token))
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "新名称"

    # 删除
    r = client.delete(f"{API}/{code}", headers=_auth(admin_token))
    assert r.status_code == 200
    assert r.json()["code"] == 0
    r = client.get(f"{API}/{code}", headers=_auth(admin_token))
    assert r.json()["code"] == 404


def test_dict_item_crud_and_dedup(client, admin_token):
    data = _create_type(client, admin_token, items=[])
    code = data["code"]

    # 新增字典项
    r = client.post(
        f"{API}/{code}/items",
        json={"label": "红色", "value": "red", "sort": 1, "ext": "#f00"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    item = r.json()["data"]
    assert item["value"] == "red"

    # 同类型 value 去重 → 业务 400
    r = client.post(
        f"{API}/{code}/items",
        json={"label": "红色2", "value": "red"},
        headers=_auth(admin_token),
    )
    assert r.json()["code"] == 400

    # 更新字典项（停用）
    r = client.put(
        f"{API}/items/{item['id']}",
        json={"enabled": False, "label": "深红"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    assert r.json()["data"]["enabled"] is False
    assert r.json()["data"]["label"] == "深红"

    # enabled_only 下拉过滤后为空
    r = client.get(f"{API}/{code}/items", params={"enabled_only": True}, headers=_auth(admin_token))
    assert r.status_code == 200
    assert r.json()["data"] == []

    # 删除字典项
    r = client.delete(f"{API}/items/{item['id']}", headers=_auth(admin_token))
    assert r.json()["code"] == 0
    r = client.get(f"{API}/{code}/items", headers=_auth(admin_token))
    assert r.json()["data"] == []


def test_system_dict_readonly(client, admin_token):
    """system=True 的类型不可删；其字典项不可删（可停用）。"""
    data = _create_type(client, admin_token, items=[{"label": "X", "value": "x"}])
    code = data["code"]
    item_id = data["items"][0]["id"]

    # 直接置 system=True（模拟系统内置种子）
    db = SessionLocal()
    dt = db.query(DictType).filter(DictType.code == code).first()
    dt.system = True
    db.commit()
    db.close()

    # 删类型 → 业务 400
    r = client.delete(f"{API}/{code}", headers=_auth(admin_token))
    assert r.status_code == 200
    assert r.json()["code"] == 400

    # 删字典项 → 业务 400
    r = client.delete(f"{API}/items/{item_id}", headers=_auth(admin_token))
    assert r.json()["code"] == 400

    # 停用字典项仍允许
    r = client.put(f"{API}/items/{item_id}", json={"enabled": False}, headers=_auth(admin_token))
    assert r.json()["code"] == 0


def test_dict_unauthorized(client):
    r = client.get(API)
    assert r.status_code == 401

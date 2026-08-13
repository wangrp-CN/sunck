"""隐患治理闭环集成测试：CRUD / 状态机 / 逾期 / 统计 / 软删 / 筛选。

均复用 conftest 的 client / admin_token（真实 dev DB）；超管绕过权限与数据范围，
因此本文件聚焦业务正确性（状态机合法性、逾期判定、统计口径、软删隔离）。
清理按 uid 前缀进行，避免污染 dev DB。
"""

import uuid

import pytest

from app.core.database import SessionLocal
from app.model.hazard import Hazard

API = "/api/v1/hazards"

# 记录本模块创建的隐患 id，测试结束后硬删，避免污染 dev DB
_CREATED: list[int] = []


@pytest.fixture(autouse=True)
def _cleanup_hazards():
    yield
    if _CREATED:
        db = SessionLocal()
        db.query(Hazard).filter(Hazard.id.in_(_CREATED)).delete(synchronize_session=False)
        db.commit()
        db.close()
        _CREATED.clear()


def _u(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _post_hazard(client, token, **over):
    body = {
        "title": over.get("title", _u("隐患")),
        "level": over.get("level", "一般"),
        "category": over.get("category", "施工安全"),
        "source": over.get("source", "人工"),
        "project_id": over.get("project_id"),
        "assignee_id": over.get("assignee_id"),
        "due_at": over.get("due_at"),
        "discovered_by_name": over.get("discovered_by_name", "测试员"),
    }
    r = client.post(API, json=body, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    _CREATED.append(data["id"])
    return data


def test_hazard_crud_and_transition(client, admin_token):
    # 创建（待整改）
    h = _post_hazard(client, admin_token, title=_u("桥墩杂物"), level="较大")
    hid = h["id"]
    assert h["status"] == "待整改"
    assert h["level"] == "较大"

    # 列表可见
    r = client.get(API, headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()["data"]["items"]]
    assert hid in ids

    # 详情
    r = client.get(f"{API}/{hid}", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    assert r.json()["data"]["id"] == hid

    # 非法流转：待整改直接复核通过 → 业务码 400（平台统一：BusinessError 返回 HTTP 200 + body code）
    r = client.post(
        f"{API}/{hid}/transition",
        json={"action": "verify_pass", "note": "x"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["code"] == 400, r.json()
    assert "不允许" in r.json()["message"]

    # 待整改 → 开始整改 → 整改中
    r = client.post(
        f"{API}/{hid}/transition",
        json={"action": "start_rectify"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "整改中"

    # 整改中 → 提交整改（需说明）→ 待复核
    r = client.post(
        f"{API}/{hid}/transition",
        json={"action": "submit_rectify", "note": "已清理并设置警示"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["status"] == "待复核"
    assert d["rectify_note"] == "已清理并设置警示"

    # 待复核 → 复核通过并销号 → 已销号（闭环）
    r = client.post(
        f"{API}/{hid}/transition",
        json={"action": "verify_pass", "note": "现场复核合格"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["status"] == "已销号"
    assert d["closed_at"] is not None
    assert d["verify_by_name"] is not None


def test_hazard_reject_and_reopen(client, admin_token):
    h = _post_hazard(client, admin_token, title=_u("驳回用例"))
    hid = h["id"]
    # 待整改 → 驳回 → 已驳回
    r = client.post(
        f"{API}/{hid}/transition",
        json={"action": "reject", "note": "非安全隐患"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "已驳回"
    # 已驳回 → 重新打开 → 待整改
    r = client.post(
        f"{API}/{hid}/transition",
        json={"action": "reopen"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "待整改"


def test_hazard_overdue_and_stats(client, admin_token):
    # 超期隐患：过去期限 + 未终态
    _post_hazard(
        client,
        admin_token,
        title=_u("超期隐患"),
        level="重大",
        due_at="2020-01-01T00:00:00",
    )
    # 逾期筛选
    r = client.get(
        API, params={"overdue": True}, headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert any(i["is_overdue"] for i in items), "应包含超期隐患"

    # 统计：超期数 >= 1
    r = client.get(f"{API}/stats", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    stats = r.json()["data"]
    assert stats["overdue"] >= 1
    assert stats["total"] >= 1
    assert "重大" in stats["by_level"]


def test_hazard_update_and_soft_delete(client, admin_token):
    h = _post_hazard(client, admin_token, title=_u("待删隐患"), category="环境")
    hid = h["id"]
    # 更新
    r = client.put(
        f"{API}/{hid}",
        json={"category": "管理", "title": "已改名"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["category"] == "管理"

    # 软删除
    r = client.delete(f"{API}/{hid}", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200

    # 删除后详情不可见（软删隔离）
    r = client.get(f"{API}/{hid}", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 404


def test_hazard_filter_by_level(client, admin_token):
    _post_hazard(client, admin_token, title=_u("等级筛选-A"), level="一般")
    _post_hazard(client, admin_token, title=_u("等级筛选-B"), level="低")
    r = client.get(API, params={"level": "低"}, headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert items and all(i["level"] == "低" for i in items)


def test_hazard_create_boundary_and_invalid(client, admin_token):
    """边界/异常：缺标题、日期格式非法 -> 参数校验失败(422)；空标题被接受。"""
    H = {"Authorization": f"Bearer {admin_token}"}

    # 异常：缺标题 -> 422
    r = client.post(API, json={"level": "一般"}, headers=H)
    assert r.status_code == 200 and r.json()["code"] == 422, r.text

    # 异常：due_at 格式非法 -> 422
    r = client.post(API, json={"title": _u("日期异常"), "due_at": "不是日期"}, headers=H)
    assert r.status_code == 200 and r.json()["code"] == 422, r.text

    # 边界：空标题("")按「标题不能为空」业务校验拒绝(400)
    r = client.post(API, json={"title": ""}, headers=H)
    assert r.status_code == 200 and r.json()["code"] == 400, r.text


def test_hazard_transition_requires_note(client, admin_token):
    """流转边界：需填说明/意见的动作在缺说明时拒绝(400)。"""
    h = _post_hazard(client, admin_token, title=_u("需说明链路"))
    hid = h["id"]
    H = {"Authorization": f"Bearer {admin_token}"}

    # 待整改 -> 开始整改 -> 整改中
    r = client.post(f"{API}/{hid}/transition", json={"action": "start_rectify"}, headers=H)
    assert r.status_code == 200, r.text

    # 整改中 -> 提交整改(缺说明) -> 400
    r = client.post(f"{API}/{hid}/transition", json={"action": "submit_rectify"}, headers=H)
    assert r.status_code == 200 and r.json()["code"] == 400, r.text
    assert "整改说明" in r.json()["message"]

    # 整改中 -> 提交整改(带说明) -> 待复核
    r = client.post(
        f"{API}/{hid}/transition", json={"action": "submit_rectify", "note": "已整改"}, headers=H
    )
    assert r.status_code == 200 and r.json()["data"]["status"] == "待复核", r.text

    # 待复核 -> 复核通过(缺意见) -> 400
    r = client.post(f"{API}/{hid}/transition", json={"action": "verify_pass"}, headers=H)
    assert r.status_code == 200 and r.json()["code"] == 400, r.text
    assert "复核意见" in r.json()["message"]


def test_hazard_reject_requires_reason(client, admin_token):
    """边界：待整改 -> 驳回(缺原因) 需填写原因(400)。"""
    h = _post_hazard(client, admin_token, title=_u("驳回需原因"))
    hid = h["id"]
    H = {"Authorization": f"Bearer {admin_token}"}
    r = client.post(f"{API}/{hid}/transition", json={"action": "reject"}, headers=H)
    assert r.status_code == 200 and r.json()["code"] == 400, r.text
    assert "原因" in r.json()["message"]


def test_hazard_transition_invalid_action(client, admin_token):
    """异常：非法流转动作 -> 400（动作校验先于状态校验）。"""
    h = _post_hazard(client, admin_token, title=_u("非法动作"))
    hid = h["id"]
    H = {"Authorization": f"Bearer {admin_token}"}
    r = client.post(f"{API}/{hid}/transition", json={"action": "fly"}, headers=H)
    assert r.status_code == 200 and r.json()["code"] == 400, r.text
    assert "非法的流转动作" in r.json()["message"]

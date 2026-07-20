"""通用附件端点回归测试：上传 / 列表 / 删除 / 预签名 + 负例。

依赖本机 MinIO（127.0.0.1:9000, minioadmin/minioadmin, 桶 rail-monitor）。
若 MinIO 不可达，整个模块自动跳过。

覆盖：
- POST /v1/attachments/upload  按 entity_type+entity_id 上传多文件
- GET  /v1/attachments         列出某实体的有效附件
- DELETE /v1/attachments/{id}  软删后列表为空、预览 404
- GET  /v1/attachments/presigned
- 负例：缺 entity_type → 422；entity_id<=0 → 400
"""

import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.database import SessionLocal
from app.main import app
from app.model.attachment import Attachment

# ---- MinIO 可用性探测 ------------------------------------------------------
minio_ok = False
try:  # pragma: no cover - 环境探测
    from app.core import minio_client as mcio

    mcio.ensure_bucket()
    minio_ok = True
except Exception as exc:  # noqa: BLE001
    pytestmark = pytest.mark.skip(reason=f"MinIO 不可用，跳过附件测试：{exc}")


def _uid() -> int:
    # 用一个不太可能碰撞的正整数作为虚拟 entity_id
    return 900000 + secrets.randbelow(90000)


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


def _cleanup(entity_type: str, entity_id: int) -> None:
    db = SessionLocal()
    try:
        db.execute(
            delete(Attachment).where(
                Attachment.entity_type == entity_type,
                Attachment.entity_id == entity_id,
            )
        )
        db.commit()
    finally:
        db.close()


def test_attachment_upload_list_delete(client, admin_token):
    """上传 → 列表可见 → 软删 → 列表为空 + 对象预览 404。"""
    eid = _uid()
    etype = "work_plan"
    try:
        files = [
            ("files", ("a.png", b"attach-a-0123456789", "image/png")),
            ("files", ("b.png", b"attach-b-abcdefghij", "image/png")),
        ]
        r = client.post(
            "/api/v1/attachments/upload",
            headers=_headers(admin_token),
            data={"entity_type": etype, "entity_id": eid},
            files=files,
        )
        assert r.status_code == 200, r.text
        created = r.json()["data"]
        assert len(created) == 2
        for c in created:
            assert c["entity_type"] == etype
            assert c["entity_id"] == eid
            assert c["media_key"].startswith(f"{etype}/{eid}/")

        # 列表可见（2 条）
        r = client.get(
            "/api/v1/attachments",
            headers=_headers(admin_token),
            params={"entity_type": etype, "entity_id": eid},
        )
        assert r.status_code == 200, r.text
        rows = r.json()["data"]
        assert len(rows) == 2
        del_id = rows[0]["id"]

        # 删除一条
        r = client.delete(f"/api/v1/attachments/{del_id}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text

        # 列表剩 1 条
        r = client.get(
            "/api/v1/attachments",
            headers=_headers(admin_token),
            params={"entity_type": etype, "entity_id": eid},
        )
        assert r.status_code == 200, r.text
        assert len(r.json()["data"]) == 1

        # 被删对象预览 404（软删同时删了 MinIO 对象）
        del_key = [c["media_key"] for c in created if c["id"] == del_id][0]
        r = client.get(f"/api/v1/media/{del_key}")
        assert r.status_code == 404

        # 重复删除 → 404
        r = client.delete(f"/api/v1/attachments/{del_id}", headers=_headers(admin_token))
        assert r.status_code == 404
    finally:
        _cleanup(etype, eid)


def test_attachment_presigned(client, admin_token):
    """上传后取预签名 URL。"""
    eid = _uid()
    etype = "device"
    try:
        files = [("files", ("d.png", b"device-attach-xxxxxx", "image/png"))]
        r = client.post(
            "/api/v1/attachments/upload",
            headers=_headers(admin_token),
            data={"entity_type": etype, "entity_id": eid},
            files=files,
        )
        assert r.status_code == 200, r.text
        key = r.json()["data"][0]["media_key"]
        r = client.get(
            "/api/v1/attachments/presigned",
            headers=_headers(admin_token),
            params={"key": key},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["url"].startswith("http")
    finally:
        _cleanup(etype, eid)


def test_attachment_list_empty_for_unknown_entity(client, admin_token):
    """未知实体列表返回空数组。"""
    r = client.get(
        "/api/v1/attachments",
        headers=_headers(admin_token),
        params={"entity_type": "nope", "entity_id": _uid()},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"] == []


def test_attachment_upload_missing_entity_type(client, admin_token):
    """缺 entity_type → 参数校验失败。

    本项目对 RequestValidationError 统一返回 HTTP 200 + body.code=422，
    故断言 body 内的业务 code 而非 HTTP 状态码。
    """
    files = [("files", ("x.png", b"data", "image/png"))]
    r = client.post(
        "/api/v1/attachments/upload",
        headers=_headers(admin_token),
        data={"entity_id": _uid()},
        files=files,
    )
    assert r.json()["code"] == 422, r.text


def test_attachment_upload_invalid_entity_id(client, admin_token):
    """entity_id<=0 → 400（业务校验）。"""
    files = [("files", ("x.png", b"data", "image/png"))]
    r = client.post(
        "/api/v1/attachments/upload",
        headers=_headers(admin_token),
        data={"entity_type": "work_plan", "entity_id": 0},
        files=files,
    )
    assert r.status_code == 400, r.text


def test_attachment_upload_requires_auth(client):
    """未认证上传被拦截。"""
    files = [("files", ("x.png", b"data", "image/png"))]
    r = client.post(
        "/api/v1/attachments/upload",
        data={"entity_type": "work_plan", "entity_id": _uid()},
        files=files,
    )
    assert r.status_code in (401, 403), r.text

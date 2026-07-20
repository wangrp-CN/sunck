"""媒体端点回归测试：上传 / 预览(Range) / 删除 / 预签名 + 告警媒体挂载。

依赖本机 MinIO（127.0.0.1:9000, minioadmin/minioadmin, 桶 rail-monitor）。
若 MinIO 不可达，整个模块自动跳过（不阻塞其它测试）。

覆盖：
- POST /v1/media/upload      认证多文件上传，返回 key / 预览 url / 元信息
- GET  /v1/media/{key}       公共预览：完整 200 + Range 206（视频拖动）
- GET  /v1/media/presigned   预签名直连 URL
- DELETE /v1/media/{key}     删除后预览 404
- PUT  /v1/alarms/{id}/media 告警媒体全量挂载，列表回读一致
"""

import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.database import SessionLocal
from app.main import app
from app.model.alarm import Alarm
from app.model.project import Project

# ---- MinIO 可用性探测：不可达则跳过整个模块 --------------------------------
minio_ok = False
try:  # pragma: no cover - 环境探测
    from app.core import minio_client as mcio

    mcio.ensure_bucket()
    minio_ok = True
except Exception as exc:  # noqa: BLE001
    pytestmark = pytest.mark.skip(reason=f"MinIO 不可用，跳过媒体测试：{exc}")


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


def test_media_upload_preview_range_delete(client, admin_token):
    """完整链路：上传 → 完整预览 → Range 预览 206 → 删除 → 预览 404。"""
    payload = bytes(range(256)) * 8  # 2048 字节，便于 Range 断言
    files = [("files", ("probe.bin", payload, "application/octet-stream"))]
    r = client.post(
        "/api/v1/media/upload",
        headers=_headers(admin_token),
        data={"prefix": "tests"},
        files=files,
    )
    assert r.status_code == 200, r.text
    metas = r.json()["data"]
    assert len(metas) == 1
    key = metas[0]["key"]
    assert key.startswith("tests/")
    assert metas[0]["size"] == len(payload)

    try:
        # 完整预览 200
        r = client.get(f"/api/v1/media/{key}")
        assert r.status_code == 200, r.text
        assert r.headers.get("accept-ranges") == "bytes"
        assert int(r.headers["content-length"]) == len(payload)
        assert r.content == payload

        # Range 预览 206
        r = client.get(f"/api/v1/media/{key}", headers={"Range": "bytes=0-99"})
        assert r.status_code == 206, r.text
        assert r.headers["content-range"] == f"bytes 0-99/{len(payload)}"
        assert int(r.headers["content-length"]) == 100
        assert r.content == payload[:100]
    finally:
        # 删除
        r = client.delete(f"/api/v1/media/{key}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text

    # 删除后预览 404
    r = client.get(f"/api/v1/media/{key}")
    assert r.status_code == 404


def test_media_upload_requires_auth(client):
    """未认证上传被拦截。"""
    files = [("files", ("x.bin", b"hello", "application/octet-stream"))]
    r = client.post("/api/v1/media/upload", files=files)
    assert r.status_code in (401, 403), r.text


def test_media_presigned(client, admin_token):
    """预签名 URL 返回 presigned_url 字段。"""
    files = [("files", ("p.bin", b"presign-data-0123456789", "application/octet-stream"))]
    r = client.post("/api/v1/media/upload", headers=_headers(admin_token), files=files)
    assert r.status_code == 200, r.text
    key = r.json()["data"][0]["key"]
    try:
        r = client.get(
            "/api/v1/media/presigned",
            headers=_headers(admin_token),
            params={"key": key},
        )
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert d["key"] == key
        assert d["presigned_url"].startswith("http")
    finally:
        client.delete(f"/api/v1/media/{key}", headers=_headers(admin_token))


def test_media_safe_key_rejected(client):
    """非法 key（路径穿越）被 400 拒绝。"""
    r = client.get("/api/v1/media/../etc/passwd")
    assert r.status_code in (400, 404), r.text


def test_alarm_media_mount_and_readback(client, admin_token):
    """告警媒体全量挂载：PUT /media 后列表回读一致。"""
    u = _uid()
    proj_id = None
    aid = None
    key = None
    try:
        # 直接建项目 + 告警（dept_id 可空；admin 数据范围为全部，可见）
        db = SessionLocal()
        try:
            p = Project(name=f"PM{u}_媒体", status="在建")
            db.add(p)
            db.flush()
            proj_id = p.id
            a = Alarm(
                project_id=proj_id,
                alarm_type="fence_intrusion",
                device_type="locate",
                device_name="媒体测试设备",
                device_no=f"DN{u}",
                alarm_info=f"ALM{u}",
                alarm_status="告警开始",
                alarm_level="严重",
                handle_status="待处理",
            )
            db.add(a)
            db.commit()
            aid = a.id
        finally:
            db.close()

        # 上传一个媒体，拿到预览 url
        files = [("files", ("evi.bin", b"evidence-bytes-xxxxxxxx", "image/png"))]
        r = client.post(
            "/api/v1/media/upload",
            headers=_headers(admin_token),
            data={"prefix": f"alarms/{aid}"},
            files=files,
        )
        assert r.status_code == 200, r.text
        meta = r.json()["data"][0]
        key = meta["key"]
        url = meta["url"]

        # 挂载到告警（含重复，应去重）
        r = client.put(
            f"/api/v1/alarms/{aid}/media",
            headers=_headers(admin_token),
            json={"urls": [url, url]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["media_urls"] == [url]

        # 列表回读一致
        r = client.get(
            "/api/v1/alarms",
            headers=_headers(admin_token),
            params={"project_id": proj_id},
        )
        assert r.status_code == 200, r.text
        found = [it for it in r.json()["data"]["items"] if it["id"] == aid]
        assert found, "告警未出现在列表"
        assert found[0]["media_urls"] == [url]
    finally:
        if key:
            client.delete(f"/api/v1/media/{key}", headers=_headers(admin_token))
        db = SessionLocal()
        try:
            if aid:
                db.execute(delete(Alarm).where(Alarm.id == aid))
            if proj_id:
                db.execute(delete(Project).where(Project.id == proj_id))
            db.commit()
        finally:
            db.close()

"""媒体上传并发 / 线程池隔离回归测试（不依赖 MinIO）。

验证 #12 修复：upload_media 改为 async，多文件经专用线程池
`minio_client.UPLOAD_EXECUTOR` 并发上传，不再占用 FastAPI 默认 anyio
线程池（承载 DB 查询等同步路由），避免大文件上传占满线程池、饿死 API 查询。

通过 mock `upload_object` 模拟阻塞 IO + 记录调度线程名，断言：
- 上传在专用池（线程名前缀 `minio-upload`）
- 多文件并发（总耗时远低于串行）
"""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.core import minio_client as mcio
from app.main import app

N_PER_FILE_SLEEP = 0.15  # 模拟单个大文件 MinIO 阻塞 IO 耗时（秒）


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_token(client):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin@123456"})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


def test_upload_concurrent_on_dedicated_executor(client, admin_token, monkeypatch):
    """多文件应并发上传到专用线程池，且不占用默认 anyio 线程池。"""
    names: list[str] = []
    saw_stream: list[bool] = []

    def fake_upload(object_name, data, length, content_type):
        # 记录调度线程名（验证专用池隔离）
        names.append(threading.current_thread().name)
        # 验证走流式（data 是可读二进制流，而非一次性读进内存的 bytes）
        saw_stream.append(hasattr(data, "read"))
        # 模拟 MinIO 阻塞 IO
        time.sleep(N_PER_FILE_SLEEP)

    # media.py 经 `from ... import upload_object` 绑定了本地名，需 patch 该引用点
    monkeypatch.setattr("app.api.v1.media.upload_object", fake_upload)
    # 避免真实建桶网络 IO
    monkeypatch.setattr(mcio, "ensure_bucket", lambda: None)

    n = 4
    files = [("files", (f"f{i}.bin", b"x" * 1024, "application/octet-stream")) for i in range(n)]
    t0 = time.monotonic()
    r = client.post(
        "/api/v1/media/upload",
        headers={"Authorization": f"Bearer {admin_token}"},
        files=files,
    )
    elapsed = time.monotonic() - t0

    assert r.status_code == 200, r.text
    metas = r.json()["data"]
    assert len(metas) == n
    assert len(names) == n, names

    # 1) 专用线程池隔离：线程名前缀应为 minio-upload（而非 anyio 默认池）
    assert all(nm.startswith("minio-upload") for nm in names), names
    # 2) 流式上传：data 必须是可读流
    assert all(saw_stream), saw_stream
    # 3) 并发：总耗时远低于串行 n*SLEEP（空出余量应对调度开销）
    serial = N_PER_FILE_SLEEP * n
    assert elapsed < serial * 0.8, f"疑似串行上传：elapsed={elapsed:.3f}s >= {serial*0.8:.3f}s"


def test_upload_size_limit_still_enforced(client, admin_token, monkeypatch):
    """大小校验仍生效：超 100MB 单文件返回 413，且不触发上传。"""
    called = []

    def fake_upload(object_name, data, length, content_type):
        called.append(object_name)

    monkeypatch.setattr("app.api.v1.media.upload_object", fake_upload)
    monkeypatch.setattr(mcio, "ensure_bucket", lambda: None)

    big = b"x" * (101 * 1024 * 1024)  # 略超 100MB
    files = [("files", ("huge.bin", big, "application/octet-stream"))]
    r = client.post(
        "/api/v1/media/upload",
        headers={"Authorization": f"Bearer {admin_token}"},
        files=files,
    )
    assert r.status_code == 413, r.text
    assert called == [], "超限文件不应进入上传"

"""MinIO 对象存储客户端封装（单例）。

复用方案A 原生 MinIO 服务（127.0.0.1:9000 / minioadmin / 桶 rail-monitor）。
提供：
- 惰性单例客户端
- 桶存在性保证（首次调用自动建桶）
- 对象上传 / 下载（支持字节区间，用于视频拖动）/ 删除 / 预签名 URL
- 媒体对象 key 生成（按日期分目录 + UUID，避免冲突）

对外统一走本模块，避免在各路由里重复初始化客户端。
"""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from minio import Minio

from app.config import settings

# 媒体桶（与 app/config.py minio_bucket 一致）
BUCKET = settings.minio_bucket

_client: Minio | None = None
_bucket_ready = False
_bucket_lock = threading.Lock()

# 专用上传线程池：隔离 MinIO 阻塞 IO，避免占满 FastAPI 默认 anyio 线程池
# （该池还承载 DB 查询等同步路由）。容量受限以限制并发上传数，
# 防止大文件上传打爆系统线程。可用 MINIO_UPLOAD_WORKERS 调优。
UPLOAD_MAX_WORKERS = int(os.getenv("MINIO_UPLOAD_WORKERS", "8"))
UPLOAD_EXECUTOR = ThreadPoolExecutor(
    max_workers=UPLOAD_MAX_WORKERS, thread_name_prefix="minio-upload"
)


def get_client() -> Minio:
    """返回惰性单例 MinIO 客户端。"""
    global _client
    if _client is None:
        _client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
    return _client


def ensure_bucket() -> None:
    """确保媒体桶存在（幂等，仅首次真正建桶）。线程安全。"""
    global _bucket_ready
    if _bucket_ready:
        return
    with _bucket_lock:
        if _bucket_ready:
            return
        client = get_client()
        if not client.bucket_exists(BUCKET):
            client.make_bucket(BUCKET)
        _bucket_ready = True


def gen_key(prefix: str = "", ext: str = "") -> str:
    """生成对象 key：{prefix}/YYYY/MM/DD/{uuid}{ext}。

    prefix 用于业务归类（如 alarms/123），ext 含点号（如 .jpg）。
    """
    now = datetime.now()
    seg = os.path.join(
        prefix,
        f"{now.year:04d}",
        f"{now.month:02d}",
        f"{now.day:02d}",
        uuid.uuid4().hex,
    )
    if ext:
        seg = seg + ext
    # 统一使用正斜杠（MinIO/对象存储 key 规范）
    return seg.replace("\\", "/")


def upload_object(
    object_name: str, data, length: int, content_type: str = "application/octet-stream"
) -> None:
    """上传对象到媒体桶。data 为可读二进制流。"""
    ensure_bucket()
    get_client().put_object(
        BUCKET, object_name, data=data, length=length, content_type=content_type
    )


def stat_object(object_name: str):
    """返回对象元信息（含 size / content_type / etag）。"""
    ensure_bucket()
    return get_client().stat_object(BUCKET, object_name)


def get_object_range(object_name: str, offset: int = 0, length: int = 0):
    """按字节区间读取对象；length=0 表示读到末尾。返回可读流。"""
    ensure_bucket()
    return get_client().get_object(BUCKET, object_name, offset=offset, length=length)


def remove_object(object_name: str) -> None:
    """删除对象。"""
    ensure_bucket()
    get_client().remove_object(BUCKET, object_name)


def presigned_get_url(object_name: str, expires: int = 3600) -> str:
    """生成预签名 GET URL（默认 1 小时有效）。

    若配置了 minio_public_url（生产经 nginx /files/ 同源代理），将签名 URL 中的
    内部端点替换为公网基址，使外部浏览器可直连加载媒体；缺省使用内部端点（开发机直连）。
    """
    ensure_bucket()
    url = get_client().presigned_get_object(BUCKET, object_name, expires=timedelta(seconds=expires))
    public = settings.minio_public_url
    if public and settings.minio_endpoint:
        scheme = "https" if settings.minio_secure else "http"
        internal = f"{scheme}://{settings.minio_endpoint}"
        if url.startswith(internal):
            url = public + url[len(internal) :]
    return url


def public_url(object_name: str) -> str:
    """返回经后端代理的预览 URL（前端 <img>/<video> 直接用，无需签名）。"""
    return f"/api/v1/media/{object_name}"

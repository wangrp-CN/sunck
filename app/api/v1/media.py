"""媒体管理路由：上传 / 预览 / 删除 / 预签名。

- POST /upload          认证后多文件上传到 MinIO 媒体桶，返回可预览的 url
- GET  /{key:path}     公共预览（供 <img>/<video> 直接使用），支持 Range 视频拖动
- DELETE /{key:path}   认证后删除对象
- GET  /presigned      认证后获取对象预签名 URL（可选，便于直连 MinIO）

预览接口不做鉴权，以便浏览器 <img>/<video> 直接引用（对象存储本身按 key 隔离，
且 key 为 UUID，无法被猜测）。这是**有意的设计权衡**（可用性优先，详见 OPTIMIZATION_REPORT #10）：
真正的部门级隔离需前端改走预签名 URL（`minio_client.presigned_get_url`）并摒弃裸 <img> 引用，
列入后续单独立项；本轮保持现状，以避免破坏前端媒体展示链路。
统一返回 ApiResponse；data 字段承载实际负载（前端 http<T> 自动解包）。
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core import minio_client as mcio
from app.core.deps import get_current_user
from app.core.minio_client import UPLOAD_EXECUTOR, upload_object
from app.core.responses import ApiResponse
from app.model.system import User

router = APIRouter(tags=["媒体管理"])

MAX_FILE_BYTES = 100 * 1024 * 1024  # 单文件上限 100MB
_CHUNK = 1 << 20  # 1MB 流式分块


class MediaMeta(BaseModel):
    key: str
    url: str
    filename: str
    content_type: str
    size: int
    bucket: str
    presigned_url: str | None = None


def _safe_key(key: str) -> str:
    """校验对象 key 合法（禁止路径穿越 / 绝对路径）。"""
    if not key or key.startswith("/") or ".." in key.split("/"):
        raise HTTPException(status_code=400, detail="非法的对象 key")
    return key


def _iter_stream(resp, chunk: int = _CHUNK):
    try:
        while True:
            b = resp.read(chunk)
            if not b:
                break
            yield b
    finally:
        resp.close()


@router.post("/upload", summary="上传媒体文件", response_model=ApiResponse)
async def upload_media(
    files: Annotated[list[UploadFile], File(description="媒体文件（图片/视频）")],
    prefix: Annotated[str, Form(description="业务归类前缀，如 alarms/123")] = "",
    _: User = Depends(get_current_user),
) -> ApiResponse:
    """上传一个或多个文件到 MinIO 媒体桶，返回 key / 预览 url / 元信息列表。

    上传在专用线程池（UPLOAD_EXECUTOR）**并发**执行，不占用 FastAPI 默认
    anyio 线程池（该池还承载 DB 查询等同步路由），避免大文件上传占满线程池、
    饿死其它 API 查询。多文件并行上传缩短整体耗时。
    """
    if not files:
        raise HTTPException(status_code=400, detail="未提供文件")

    loop = asyncio.get_running_loop()
    # 先确保桶存在（仅首次真正网络 IO），后续并发上传的 ensure_bucket 直接短路
    await loop.run_in_executor(UPLOAD_EXECUTOR, mcio.ensure_bucket)

    async def _upload_one(f: UploadFile) -> MediaMeta:
        if f.size is not None and f.size > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"文件 {f.filename or ''} 超过单文件上限 {MAX_FILE_BYTES // (1024 * 1024)}MB",
            )
        ext = os.path.splitext(f.filename or "")[1].lower()
        key = mcio.gen_key(prefix=prefix, ext=ext)
        length = f.size if f.size is not None else -1
        # starlette 的 UploadFile.file 是可读二进制流（流式直传，内存不爆）；
        # 放专用线程池执行，避免阻塞默认 anyio 线程池
        await loop.run_in_executor(
            UPLOAD_EXECUTOR,
            upload_object,
            key,
            f.file,
            length,
            f.content_type or "application/octet-stream",
        )
        return MediaMeta(
            key=key,
            url=mcio.public_url(key),
            filename=f.filename or key,
            content_type=f.content_type or "application/octet-stream",
            size=length,
            bucket=mcio.BUCKET,
            presigned_url=mcio.presigned_get_url(key),
        )

    # 并发上传所有文件
    results = list(await asyncio.gather(*(_upload_one(f) for f in files)))
    return ApiResponse.success(data=results)


@router.get("/presigned", summary="获取预签名 URL", response_model=ApiResponse)
def presigned_media(
    key: Annotated[str, Query(description="对象 key")],
    expiry: Annotated[int, Query(description="有效期秒")] = 3600,
    _: User = Depends(get_current_user),
) -> ApiResponse:
    """认证后生成预签名 GET URL（便于前端直连 MinIO，绕过代理）。

    NOTE: 必须定义在 `/{key:path}` 之前，否则会被通配路由吞掉（key='presigned'）。
    """
    _safe_key(key)
    url = mcio.presigned_get_url(key, expires=expiry)
    return ApiResponse.success(data={"key": key, "url": mcio.public_url(key), "presigned_url": url})


@router.get("/{key:path}", summary="预览媒体对象（公共）")
def preview_media(key: str, request: Request) -> StreamingResponse:
    """公共预览：图片/视频直接用；支持 HTTP Range 以实现视频拖动。"""
    _safe_key(key)
    try:
        stat = mcio.stat_object(key)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="媒体对象不存在")

    size = stat.size
    content_type = stat.content_type or "application/octet-stream"

    # 解析 Range 头
    range_hdr = request.headers.get("range")
    start, end = 0, size - 1
    partial = False
    if range_hdr:
        m = re.match(r"bytes=(\d*)-(\d*)", range_hdr)
        if m:
            g1, g2 = m.group(1), m.group(2)
            if g1:
                start = int(g1)
            if g2:
                end = int(g2)
            else:
                end = size - 1
            start = max(0, min(start, size - 1))
            end = max(start, min(end, size - 1))
            partial = True

    length = end - start + 1
    stream = mcio.get_object_range(key, offset=start, length=length)

    headers = {
        "Content-Type": content_type,
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Cache-Control": "public, max-age=31536000, immutable",
    }
    if stat.etag:
        headers["ETag"] = stat.etag
    status_code = 200
    if partial:
        status_code = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"

    return StreamingResponse(_iter_stream(stream), status_code=status_code, headers=headers)


@router.delete("/{key:path}", summary="删除媒体对象", response_model=ApiResponse)
def delete_media(key: str, _: User = Depends(get_current_user)) -> ApiResponse:
    """认证后删除对象（如撤回已上传但未使用的媒体）。"""
    _safe_key(key)
    mcio.remove_object(key)
    return ApiResponse.success(message="已删除")

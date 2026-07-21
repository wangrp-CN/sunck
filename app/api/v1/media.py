"""媒体管理路由：上传 / 预览 / 删除 / 预签名。

- POST /upload          认证后多文件上传到 MinIO 媒体桶，返回 key / 预览 url / 元信息
- GET  /access          认证 + 部门隔离，返回对象预签名直连 URL（前端 <img>/<video> 用）
- GET  /presigned       认证 + 部门隔离，返回预签名 URL（便于直连 MinIO）
- GET  /{key:path}     需认证预览（支持 Range 视频拖动），供特殊场景兜底
- DELETE /{key:path}   认证后删除对象

部门级隔离（OPTIMIZATION_REPORT #10 已闭环）：媒体不再匿名公开。前端展示统一改走
``/access`` 返回的 presigned_url（签名直连 MinIO，无需 Authorization 头）；``/access``
会按媒体归属项目执行数据范围校验，越权返回 404。原匿名代理预览接口已改为需认证。
统一返回 ApiResponse；data 字段承载实际负载（前端 http<T> 自动解包）。
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import minio_client as mcio
from app.core.data_scope import DataScope, apply_data_scope, resolve_entity_project_id
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope
from app.core.minio_client import UPLOAD_EXECUTOR, upload_object
from app.core.responses import ApiResponse
from app.model.alarm import Alarm
from app.model.attachment import Attachment
from app.model.project import Project
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


def _resolve_media_project(db: Session, key: str) -> Optional[int]:
    """解析媒体 key 归属的项目 ID（用于部门数据隔离）；无法归属返回 None。

    - 通用附件：按 Attachment.media_key 命中 → 解析实体 → 归属项目。
    - 告警媒体：Alarm.media_urls 存为 JSON 字符串（含代理 URL），按 key 子串
      定位归属告警 → 取其 project_id。
    """
    att = db.scalar(
        select(Attachment).where(Attachment.media_key == key, Attachment.is_deleted.is_(False))
    )
    if att is not None:
        pid = resolve_entity_project_id(db, att.entity_type, att.entity_id)
        if pid is not None:
            return pid
    alarm = db.scalar(
        select(Alarm).where(Alarm.media_urls.isnot(None), Alarm.media_urls.like(f"%{key}%"))
    )
    if alarm is not None:
        return alarm.project_id
    return None


def _media_visible(db: Session, key: str, scope: DataScope) -> bool:
    """当前用户数据范围是否可见该媒体（按归属项目判定）。

    - 先确认对象在 MinIO 中真实存在：不存在一律 404（不泄露对象是否「存在/归属」）。
    - 全部数据范围（超管）直接可见任何存在的对象。
    - 其余用户：媒体须能解析到其归属项目，且该项目落在当前用户数据范围内。
    """
    try:
        mcio.stat_object(key)
    except Exception:  # noqa: BLE001
        return False
    if scope.is_all:
        return True
    pid = _resolve_media_project(db, key)
    if pid is None:
        return False
    stmt = select(Project).where(Project.id == pid)
    stmt = apply_data_scope(stmt, Project, scope)
    return db.scalar(stmt) is not None


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


@router.get("/access", summary="获取部门隔离的预签名媒体 URL", response_model=ApiResponse)
def media_access(
    key: Annotated[str, Query(description="对象 key")],
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """获取预签名直连 URL（前端 <img>/<video> 直接使用，无需携带 Authorization）。

    部门数据隔离：仅当前用户数据范围内可见项目下的媒体可获取；越权或不存在
    一律返回 404（不泄露对象是否存在）。前端应以此返回的 presigned_url 作为
    <img>/<video> 的 src，取代原先匿名可访问的代理 URL（关闭 #10 公开缺口）。
    """
    _safe_key(key)
    if not _media_visible(db, key, scope):
        raise HTTPException(status_code=404, detail="媒体对象不存在或无权访问")
    url = mcio.presigned_get_url(key)
    return ApiResponse.success(data={"key": key, "presigned_url": url})


@router.get("/presigned", summary="获取预签名 URL（部门隔离）", response_model=ApiResponse)
def presigned_media(
    key: Annotated[str, Query(description="对象 key")],
    expiry: Annotated[int, Query(description="有效期秒")] = 3600,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """认证后生成预签名 GET URL（便于前端直连 MinIO，绕过代理）。

    与 /access 同样执行部门数据隔离校验。

    NOTE: 必须定义在 `/{key:path}` 之前，否则会被通配路由吞掉（key='presigned'）。
    """
    _safe_key(key)
    if not _media_visible(db, key, scope):
        raise HTTPException(status_code=404, detail="媒体对象不存在或无权访问")
    url = mcio.presigned_get_url(key, expires=expiry)
    return ApiResponse.success(data={"key": key, "url": mcio.public_url(key), "presigned_url": url})


@router.get("/{key:path}", summary="预览媒体对象（需认证）")
def preview_media(
    key: str,
    request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> StreamingResponse:
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

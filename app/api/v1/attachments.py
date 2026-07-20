"""通用附件路由：上传并关联到实体、列表、删除、预签名。

设计：
- 写操作（上传/删除/预签名）需登录（get_current_user）。
- 预览走公共媒体代理 /api/v1/media/{key}（见 media.py，前端 <img>/<video> 直连）。
- 部门数据隔离交由「父实体可见性」保证：UI 仅对当前用户可见的实体展示其附件，
  本路由不再额外做按 entity 的部门过滤，避免对异构实体重复实现隔离逻辑。

单文件上限 100MB（与 media.py 一致）。
"""

from __future__ import annotations

import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.data_scope import DataScope, apply_data_scope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope
from app.core.minio_client import (
    gen_key,
    presigned_get_url,
    public_url,
    remove_object,
    upload_object,
)
from app.core.responses import ApiResponse
from app.model.alarm import Alarm
from app.model.attachment import Attachment
from app.model.job import WorkPlan
from app.model.project import Project
from app.model.system import User

router = APIRouter(tags=["附件"])

# 与 media.py 保持一致
MAX_BYTES = 100 * 1024 * 1024


def _to_out(a: Attachment) -> dict:
    return {
        "id": a.id,
        "entity_type": a.entity_type,
        "entity_id": a.entity_id,
        "media_key": a.media_key,
        "url": a.url,
        "filename": a.filename,
        "content_type": a.content_type,
        "size": a.size,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "created_by": a.created_by,
    }


# ---------------------------------------------------------------------------
# 部门隔离：按 entity_type 解析父实体可见性
# ---------------------------------------------------------------------------

#: 可执行部门隔离检查的 entity_type → ORM 模型映射。
#: 不在映射中的 entity_type 不检查（保持原有行为，由 UI 保证可见性）。
_ENTITY_MODEL: dict[str, type] = {
    "work_plan": WorkPlan,
    "alarm": Alarm,
    "project": Project,
}


def _entity_visible(db: Session, entity_type: str, entity_id: int, scope: DataScope) -> bool:
    """检查当前用户的数据范围是否可见该实体。

    返回 False 表示无权访问（应返回 403 或 404）。
    scope.is_all 时无条件通过；未知 entity_type 保守放行。
    """
    if scope.is_all:
        return True
    model = _ENTITY_MODEL.get(entity_type)
    if model is None:
        return True  # 未知类型保守放行，保持现有行为
    stmt = select(model).where(model.id == entity_id)
    stmt = apply_data_scope(stmt, model, scope)
    return db.scalar(stmt) is not None


@router.post("/upload")
def upload_attachments(
    entity_type: str = Form(...),
    entity_id: int = Form(...),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    scope: DataScope = Depends(get_data_scope),
):
    """上传文件并关联到指定实体，返回 AttachmentOut 列表。

    部门数据隔离：仅当前用户数据范围内可见的实体可上传附件。
    """
    if not entity_type or entity_id <= 0:
        raise HTTPException(status_code=400, detail="entity_type/entity_id 不合法")
    if not _entity_visible(db, entity_type, entity_id, scope):
        raise HTTPException(status_code=403, detail="无权操作该实体")

    created: list[Attachment] = []
    for f in files:
        raw = f.file.read()
        if not raw:
            continue
        if len(raw) > MAX_BYTES:
            raise HTTPException(status_code=413, detail=f"文件 {f.filename} 超过 100MB 上限")
        name = f.filename or "file"
        ext = ("." + name.rsplit(".", 1)[1].lower()) if "." in name else ""
        key = gen_key(f"{entity_type}/{entity_id}", ext)
        ct = f.content_type or "application/octet-stream"
        upload_object(key, data=io.BytesIO(raw), length=len(raw), content_type=ct)
        att = Attachment(
            entity_type=entity_type,
            entity_id=entity_id,
            media_key=key,
            url=public_url(key),
            filename=name,
            content_type=ct,
            size=len(raw),
            created_by=user.id,
        )
        db.add(att)
        db.flush()
        created.append(att)

    db.commit()
    return ApiResponse.success(
        data=[_to_out(a) for a in created], message=f"已上传 {len(created)} 个附件"
    )


@router.get("")
def list_attachments(
    entity_type: str = "",
    entity_id: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    scope: DataScope = Depends(get_data_scope),
):
    """列出某实体的全部有效附件（按上传顺序）。

    部门数据隔离：仅返回当前用户数据范围内可见的实体附件。
    """
    if not entity_type or entity_id <= 0:
        return ApiResponse.success(data=[])
    if not _entity_visible(db, entity_type, entity_id, scope):
        return ApiResponse.success(data=[])
    rows = (
        db.execute(
            select(Attachment)
            .where(
                Attachment.entity_type == entity_type,
                Attachment.entity_id == entity_id,
                Attachment.is_deleted.is_(False),
            )
            .order_by(Attachment.id)
        )
        .scalars()
        .all()
    )
    return ApiResponse.success(data=[_to_out(a) for a in rows])


@router.delete("/{attachment_id}")
def delete_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    scope: DataScope = Depends(get_data_scope),
):
    """删除附件：MinIO 对象 + 软删 DB 行。

    部门数据隔离：仅当前用户数据范围内可见实体的附件可删除。
    """
    att = db.get(Attachment, attachment_id)
    if att is None or att.is_deleted:
        raise HTTPException(status_code=404, detail="附件不存在")
    if not _entity_visible(db, att.entity_type, att.entity_id, scope):
        raise HTTPException(status_code=403, detail="无权操作该实体")
    try:
        remove_object(att.media_key)
    except Exception:
        # 对象已不存在不阻塞软删
        pass
    att.is_deleted = True
    db.commit()
    return ApiResponse.success(message="已删除")


@router.get("/presigned")
def presigned(
    key: str = "",
    _: User = Depends(get_current_user),
):
    """获取某媒体对象的预签名直连 URL（可选）。"""
    if not key:
        raise HTTPException(status_code=400, detail="key 不能为空")
    return ApiResponse.success(data={"key": key, "url": presigned_get_url(key)})

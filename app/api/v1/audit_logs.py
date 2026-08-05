"""操作审计路由：分页列表（受部门数据范围约束）+ 检索元数据 + 导出。

审计记录由 `app.core.audit.AuditMiddleware` 对各写请求自动落库；本路由仅提供
受数据范围约束的查阅能力（超级管理员可见全部，部门管理员仅见本部门及以下）。
"""

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope
from app.core.responses import ApiResponse
from app.model.audit import AuditLog
from app.model.system import User
from app.service.audit_service import list_audit_logs

router = APIRouter(tags=["操作审计"])


def _parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        try:
            d = datetime.strptime(value, "%Y-%m-%d")
            return d
        except ValueError:
            return None


@router.get(
    "",
    summary="操作审计列表",
    response_model=ApiResponse,
)
def list_audits(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    scope=Depends(get_data_scope),
    module: str | None = Query(None, description="按模块过滤"),
    action: str | None = Query(None, description="按动作过滤"),
    username: str | None = Query(None, description="操作人关键字"),
    start: str | None = Query(None, description="起始时间(ISO/YYYY-MM-DD)"),
    end: str | None = Query(None, description="结束时间(ISO/YYYY-MM-DD)"),
    page: int = 1,
    size: int = 20,
) -> ApiResponse:
    page_data = list_audit_logs(
        db,
        scope,
        module=module,
        action=action,
        username=username,
        start=_parse_dt(start),
        end=_parse_dt(end),
        page=page,
        size=size,
    )
    return ApiResponse.success(data=page_data.model_dump())


@router.get(
    "/meta",
    summary="审计检索元数据",
    response_model=ApiResponse,
)
def audit_meta(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApiResponse:
    """返回库中已出现的模块 / 动作集合，供前端下拉过滤。"""
    modules = [
        m[0]
        for m in db.scalars(select(distinct(AuditLog.module)).where(AuditLog.module != "")).all()
    ]
    actions = [
        a[0]
        for a in db.scalars(select(distinct(AuditLog.action)).where(AuditLog.action != "")).all()
    ]
    return ApiResponse.success(data={"modules": modules, "actions": actions})


@router.get(
    "/export",
    summary="导出操作审计日志为 CSV",
    response_class=StreamingResponse,
)
def export_audits(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    scope=Depends(get_data_scope),
    module: str | None = Query(None, description="按模块过滤"),
    action: str | None = Query(None, description="按动作过滤"),
    username: str | None = Query(None, description="操作人关键字"),
    start: str | None = Query(None, description="起始时间"),
    end: str | None = Query(None, description="结束时间"),
) -> StreamingResponse:
    """导出过滤后的操作审计记录为 CSV 文件，最多导出 10000 条。"""
    page_data = list_audit_logs(
        db,
        scope,
        module=module,
        action=action,
        username=username,
        start=_parse_dt(start),
        end=_parse_dt(end),
        page=1,
        size=10000,
    )

    output = io.StringIO()
    output.write("\ufeff")  # UTF-8 BOM for Excel
    writer = csv.writer(output)
    writer.writerow(
        [
            "ID",
            "操作人",
            "部门ID",
            "模块",
            "动作",
            "HTTP方法",
            "路径",
            "查询串",
            "状态码",
            "客户端IP",
            "详情",
            "时间",
        ]
    )
    for item in page_data.items:
        writer.writerow(
            [
                item.id,
                item.username or "",
                item.dept_id or "",
                item.module,
                item.action,
                item.method,
                item.path,
                item.query or "",
                item.status_code,
                item.ip or "",
                item.detail or "",
                item.created_at,
            ]
        )

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=audit_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        },
    )

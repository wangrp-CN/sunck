"""系统日志路由：列表检索、元数据查询与导出。

系统日志记录应用运行时的异常、警告与关键事件，由应用内部各模块通过
``log_service.write_system_log()`` 写入。
"""

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_permissions
from app.core.responses import ApiResponse
from app.model.system import User
from app.service import log_service

router = APIRouter(tags=["系统日志"])


def _parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return None


# ── 查询 / 筛选 ───────────────────────────────────────────


@router.get("", summary="系统日志分页列表", response_model=ApiResponse)
def list_logs(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("system_log:list")),
    level: str | None = Query(None, description="日志级别: DEBUG/INFO/WARNING/ERROR/CRITICAL"),
    module: str | None = Query(None, description="来源模块"),
    keyword: str | None = Query(None, description="摘要关键字"),
    start: str | None = Query(None, description="起始时间(ISO/YYYY-MM-DD)"),
    end: str | None = Query(None, description="结束时间(ISO/YYYY-MM-DD)"),
    page: int = 1,
    size: int = 20,
) -> ApiResponse:
    page_data = log_service.list_system_logs(
        db,
        level=level,
        module=module,
        keyword=keyword,
        start=_parse_dt(start),
        end=_parse_dt(end),
        page=page,
        size=size,
    )
    return ApiResponse.success(data=page_data.model_dump())


@router.get("/meta", summary="日志检索元数据", response_model=ApiResponse)
def log_meta(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("system_log:list")),
) -> ApiResponse:
    """返回库中已出现的日志级别和模块集合，供前端下拉筛选。"""
    meta = log_service.get_system_log_meta(db)
    return ApiResponse.success(data=meta.model_dump())


@router.get("/export", summary="导出系统日志为 CSV", response_class=StreamingResponse)
def export_logs(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _=Depends(require_permissions("system_log:list")),
    level: str | None = Query(None, description="日志级别"),
    module: str | None = Query(None, description="来源模块"),
    keyword: str | None = Query(None, description="摘要关键字"),
    start: str | None = Query(None, description="起始时间"),
    end: str | None = Query(None, description="结束时间"),
) -> StreamingResponse:
    """导出过滤后的系统日志为 CSV 文件，最多导出 10000 条。"""
    page_data = log_service.list_system_logs(
        db,
        level=level,
        module=module,
        keyword=keyword,
        start=_parse_dt(start),
        end=_parse_dt(end),
        page=1,
        size=10000,
    )

    output = io.StringIO()
    output.write("\ufeff")  # UTF-8 BOM for Excel
    writer = csv.writer(output)
    writer.writerow(
        ["ID", "级别", "模块", "摘要", "详细上下文", "异常堆栈", "触发来源", "关联用户", "时间"]
    )
    for item in page_data.items:
        writer.writerow(
            [
                item.id,
                item.level,
                item.module,
                item.message,
                item.detail or "",
                item.traceback or "",
                item.source or "",
                item.user_id or "",
                item.created_at,
            ]
        )

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=system_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        },
    )

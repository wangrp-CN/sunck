"""风险健康报表导出（Phase 1 报表导出）。

- ``GET /v1/reports/risk-health/preview``：返回聚合后的风险健康报表 JSON（供前端预览）。
- ``GET /v1/reports/risk-health/export``：导出 Excel / PDF（StreamingResponse，中文名
  经 RFC5987 filename*=UTF-8'' 传递）。

数据范围经 ``get_data_scope`` 隔离（部门/项目维度），只读会话。报表拼装复用
``app.service.risk_health_report``（与定时快照同源：``risk_health_snapshot`` 表）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.data_scope import DataScope
from app.core.database import get_read_db
from app.core.deps import get_current_user, get_data_scope
from app.core.responses import ApiResponse
from app.model.system import User
from app.service.effectiveness_export import disposition_header
from app.service.risk_health_report import (
    collect_risk_health_report,
    generate_risk_health_report,
)

router = APIRouter(prefix="/reports", tags=["报表导出"])


@router.get("/risk-health/preview")
def risk_health_preview(
    db: Session = Depends(get_read_db),
    _: User = Depends(get_current_user),
    scope: DataScope = Depends(get_data_scope),
    period_type: str = Query(
        "weekly", description="统计周期：daily(日报/昨日) | weekly(周报/上周)"
    ),
) -> ApiResponse:
    """风险健康报表预览（JSON），含概览、项目风险排名、设备健康分布、Top 风险/亚健康。"""
    data = collect_risk_health_report(db, scope, period_type)
    return ApiResponse.success(data=data)


@router.get("/risk-health/export")
def risk_health_export(
    db: Session = Depends(get_read_db),
    _: User = Depends(get_current_user),
    scope: DataScope = Depends(get_data_scope),
    period_type: str = Query("weekly", description="统计周期：daily | weekly"),
    fmt: str = Query("excel", description="导出格式：excel | pdf"),
) -> StreamingResponse:
    """导出风险健康报表（Excel / PDF）。

    聚合 ``risk_health_snapshot`` 快照为日报/周报，概览 + 项目风险明细 + 设备健康明细，
    数据范围与预览一致（部门隔离）。
    """
    content, filename, media_type = generate_risk_health_report(
        db, scope, period_type=period_type, fmt=fmt
    )
    ascii_name = (
        f"risk_health_report_{period_type}.{'pdf' if (fmt or 'excel').lower() == 'pdf' else 'xlsx'}"
    )
    disposition = disposition_header(filename, ascii_name)
    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )

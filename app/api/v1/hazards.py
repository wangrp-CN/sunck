"""隐患治理闭环路由：列表/详情/增删改/状态流转/统计，带部门数据隔离与 hazard:* 权限。

- GET  /        隐患列表（筛选 + 分页 + 数据隔离）
- POST /        创建隐患（hazard:create）
- GET  /stats   统计（按状态/等级/超期，hazard:list）
- GET  /{id}    详情（hazard:list）
- PUT  /{id}    更新（hazard:update）
- DELETE /{id}  软删除（hazard:delete）
- POST /{id}/transition  状态流转（hazard:handle）
"""

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.core.data_scope import DataScope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.responses import ApiResponse
from app.model.system import User
from app.schema.hazard import (
    HAZARD_CATEGORY_OPTIONS,
    HAZARD_LEVEL_OPTIONS,
    HAZARD_SOURCE_OPTIONS,
    HAZARD_STATUS_OPTIONS,
    HazardCreate,
    HazardTransition,
    HazardUpdate,
)
from app.service import hazard_service as svc

router = APIRouter(tags=["隐患治理"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "hazards", "status": "ready"}


@router.get(
    "/options",
    summary="隐患枚举选项",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("hazard:list"))],
)
def options() -> ApiResponse:
    """返回前端下拉所需的等级/类别/来源/状态枚举。"""
    return ApiResponse.success(
        data={
            "levels": HAZARD_LEVEL_OPTIONS,
            "categories": HAZARD_CATEGORY_OPTIONS,
            "sources": HAZARD_SOURCE_OPTIONS,
            "statuses": HAZARD_STATUS_OPTIONS,
        }
    )


@router.get(
    "/stats",
    summary="隐患统计",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("hazard:list"))],
)
def stats(db=Depends(get_db), scope: DataScope = Depends(get_data_scope)) -> ApiResponse:
    """按状态/等级/超期统计（受部门数据隔离约束）。"""
    return ApiResponse.success(data=svc.hazard_stats(db, scope))


_EXPORT_COLUMNS = [
    # (key, 表头, excel宽, pdf宽mm)
    ("id", "ID", 8, 10),
    ("project_name", "项目", 20, 30),
    ("title", "隐患标题", 32, 42),
    ("level", "等级", 8, 12),
    ("category", "类别", 12, 18),
    ("status", "状态", 10, 14),
    ("is_overdue", "超期", 8, 10),
    ("assignee_name", "责任人", 12, 16),
    ("due_at", "整改期限", 20, 26),
    ("discovered_by_name", "发现人", 12, 16),
    ("discovered_at", "发现时间", 20, 26),
    ("source", "来源", 8, 12),
    ("closed_at", "销号时间", 20, 26),
]


def _fmt_dt(v) -> str:
    """datetime → 北京时间可读串（与 schema 序列化口径一致）。"""
    if v is None:
        return ""
    if isinstance(v, datetime):
        if v.tzinfo is not None:
            v = v.astimezone().replace(tzinfo=None)
        return v.strftime("%Y-%m-%d %H:%M")
    return str(v)


@router.get(
    "/export",
    summary="导出隐患报表（Excel/PDF）",
    dependencies=[Depends(require_permissions("hazard:list"))],
)
def export_hazards(
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    fmt: str = Query("excel", description="导出格式：excel | pdf"),
    project_id: int | None = None,
    level: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    overdue: bool = Query(False, description="仅看超期"),
) -> StreamingResponse:
    """按当前筛选条件导出全量隐患（受数据范围约束），与告警报表导出对称。"""
    from app.service.report_common import build_simple_excel, build_simple_pdf

    _, items = svc.list_hazards(
        db,
        scope,
        project_id=project_id,
        level=level,
        status=status,
        keyword=keyword,
        overdue_only=overdue,
        page=1,
        size=1_000_000,
    )
    rows = []
    by_status: dict[str, int] = {}
    by_level: dict[str, int] = {}
    overdue_cnt = 0
    for o in items:
        by_status[o.status] = by_status.get(o.status, 0) + 1
        by_level[o.level] = by_level.get(o.level, 0) + 1
        if o.is_overdue:
            overdue_cnt += 1
        rows.append(
            {
                "id": o.id,
                "project_name": o.project_name or "",
                "title": o.title,
                "level": o.level,
                "category": o.category or "",
                "status": o.status,
                "is_overdue": "是" if o.is_overdue else "",
                "assignee_name": o.assignee_name or "",
                "due_at": _fmt_dt(o.due_at),
                "discovered_by_name": o.discovered_by_name or "",
                "discovered_at": _fmt_dt(o.discovered_at),
                "source": o.source,
                "closed_at": _fmt_dt(o.closed_at),
            }
        )

    filters = []
    if project_id is not None:
        filters.append(f"项目ID={project_id}")
    if level:
        filters.append(f"等级={level}")
    if status:
        filters.append(f"状态={status}")
    if keyword:
        filters.append(f"关键词={keyword}")
    if overdue:
        filters.append("仅超期")
    meta = {
        "title": "涉铁工程隐患治理报表",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "filters_desc": "；".join(filters) or "全部",
    }
    summary_blocks = [
        ("按状态", sorted(by_status.items())),
        ("按等级", sorted(by_level.items())),
        ("超期情况", [("超期未闭环", overdue_cnt), ("正常", len(rows) - overdue_cnt)]),
    ]

    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    if fmt == "pdf":
        content = build_simple_pdf(_EXPORT_COLUMNS, rows, meta, summary_blocks)
        media_type = "application/pdf"
        filename = f"hazard_report_{tag}.pdf"
    else:
        content = build_simple_excel(_EXPORT_COLUMNS, rows, meta, summary_blocks)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"hazard_report_{tag}.xlsx"
    disposition = f"attachment; filename={filename}; filename*=UTF-8''{quote(filename)}"
    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


@router.get(
    "",
    summary="隐患列表",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("hazard:list"))],
)
def list_hazards(
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = None,
    level: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    overdue: bool = Query(False, description="仅看超期"),
    page: int = 1,
    size: int = 20,
) -> ApiResponse:
    """分页列出隐患，返回真实总数，施加部门数据隔离。"""
    total, items = svc.list_hazards(
        db,
        scope,
        project_id=project_id,
        level=level,
        status=status,
        keyword=keyword,
        overdue_only=overdue,
        page=page,
        size=size,
    )
    return ApiResponse.success(data={"total": total, "items": items, "page": page, "size": size})


@router.post(
    "",
    summary="创建隐患",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("hazard:create"))],
)
def create(
    req: HazardCreate,
    db=Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApiResponse:
    """创建一条隐患；发现时间缺省填当前时间。"""
    data = req.model_dump()
    out = svc.create_hazard(db, data, user.id)
    db.commit()
    return ApiResponse.success(data=out, message="隐患已创建")


@router.get(
    "/{hazard_id}",
    summary="隐患详情",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("hazard:list"))],
)
def get_one(
    hazard_id: int,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """隐患详情（数据范围内不可见返回 null）。"""
    out = svc.get_hazard(db, hazard_id, scope)
    if out is None:
        raise HTTPException(status_code=404, detail="隐患不存在或无权限访问")
    return ApiResponse.success(data=out)


@router.put(
    "/{hazard_id}",
    summary="更新隐患",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("hazard:update"))],
)
def update(
    hazard_id: int,
    req: HazardUpdate,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """局部更新隐患（仅数据范围内可见的记录）。"""
    data = {k: v for k, v in req.model_dump().items() if v is not None}
    out = svc.update_hazard(db, hazard_id, data, scope)
    if out is None:
        raise HTTPException(status_code=404, detail="隐患不存在或无权限访问")
    db.commit()
    return ApiResponse.success(data=out, message="隐患已更新")


@router.delete(
    "/{hazard_id}",
    summary="删除隐患",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("hazard:delete"))],
)
def delete(
    hazard_id: int,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """软删除隐患（仅数据范围内可见的记录）。"""
    ok = svc.delete_hazard(db, hazard_id, scope)
    if not ok:
        raise HTTPException(status_code=404, detail="隐患不存在或无权限访问")
    db.commit()
    return ApiResponse.success(data={"id": hazard_id}, message="隐患已删除")


@router.post(
    "/{hazard_id}/transition",
    summary="隐患状态流转",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("hazard:handle"))],
)
def transition(
    hazard_id: int,
    req: HazardTransition,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    user: User = Depends(get_current_user),
) -> ApiResponse:
    """执行状态机流转（待整改→整改中→待复核→已销号，含驳回/重开）。"""
    operator = user.nickname or user.username
    out = svc.transition_hazard(db, hazard_id, req.action, req.note, scope, operator_name=operator)
    db.commit()
    return ApiResponse.success(data=out, message="状态已更新")

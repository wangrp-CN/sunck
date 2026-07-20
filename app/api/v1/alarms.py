"""告警管理路由（阶段1）：列表查询 + 处置闭环（含消警回写下发）。

- GET  /   告警列表（过滤 + 部门数据隔离）
- POST /{id}/handle  处置（处理/忽略/确认/已消警）；置「已消警」时向设备下发消警指令
"""

import calendar
import json
import logging
from datetime import datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import ALARM_STATUS_CLEARED
from app.core.constants import down_topic as _down_topic
from app.core.data_scope import DataScope, apply_data_scope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.exceptions import BusinessError
from app.core.responses import ApiResponse
from app.model.alarm import Alarm, AlarmConfig
from app.model.project import Project
from app.model.system import User
from app.mqtt import client as mqtt_client
from app.mqtt import protocol
from app.service.alarm_report import (
    build_excel,
    build_excel_snapshot,
    build_pdf,
    build_pdf_snapshot,
    build_snapshot_payload,
)
from app.service.alarm_service import (
    _period_key,
    aggregate_alarms,
    handle_alarm,
    query_alarms_for_report,
    update_alarm_media,
)
from app.service.alarm_service import (
    count_alarms as svc_count_alarms,
)
from app.service.alarm_service import (
    list_alarms as svc_list_alarms,
)

logger = logging.getLogger(__name__)


def _parse_dt(s: str | None) -> datetime | None:
    """解析 ISO 时间字符串；失败抛业务错误。支持 'YYYY-MM-DD' 与完整 ISO。"""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        raise BusinessError(f"时间格式非法：{s}（应为 ISO 8601）", code=400)


def _parse_date(date: str) -> tuple[datetime, datetime]:
    """解析 'YYYY-MM-DD' 为当日 [00:00:00, 23:59:59.999999] 两个 naive datetime。

    用于报表柱状图「下钻到当日明细」的起止边界。
    """
    try:
        y, m, d = (int(x) for x in date.split("-"))
        if not (1 <= m <= 12 and 1 <= d <= 31):
            raise ValueError
        start = datetime(y, m, d, 0, 0, 0)
        end = datetime(y, m, d, 23, 59, 59, 999999)
    except (ValueError, AttributeError):
        raise BusinessError(f"日期格式非法：{date}（应为 YYYY-MM-DD）", code=400)
    return start, end


def _parse_period(granularity: str, period: str) -> tuple[datetime, datetime]:
    """把 (granularity, period) 解析为时间边界 [start, end]。

    - day:   period=YYYY-MM-DD           → 当日 00:00:00 ~ 23:59:59.999999
    - week:  period=YYYY-Www（ISO 周）   → 周一 00:00:00 ~ 周日 23:59:59.999999
    - month: period=YYYY-MM              → 当月 1 日 00:00:00 ~ 月末 23:59:59.999999
    """
    if granularity == "month":
        try:
            y, m = (int(x) for x in period.split("-"))
            if not (1 <= m <= 12):
                raise ValueError
            last = calendar.monthrange(y, m)[1]
        except (ValueError, AttributeError):
            raise BusinessError(f"月度周期格式非法：{period}（应为 YYYY-MM）", code=400)
        start = datetime(y, m, 1, 0, 0, 0)
        end = datetime(y, m, last, 23, 59, 59, 999999)
        return start, end
    if granularity == "week":
        try:
            prefix, wnum = period.split("-W")
            y, w = int(prefix), int(wnum)
            if not (1 <= w <= 53):
                raise ValueError
            # %G-W%V-%u 解析 ISO 周 → 周一日期
            monday = datetime.strptime(f"{y}-W{w:02d}-1", "%G-W%V-%u")
        except (ValueError, AttributeError):
            raise BusinessError(f"周度周期格式非法：{period}（应为 YYYY-Www）", code=400)
        sunday = monday + timedelta(days=6)
        start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        end = sunday.replace(hour=23, minute=59, second=59, microsecond=999999)
        return start, end
    # day
    return _parse_date(period)


def _enumerate_periods(granularity: str, start: datetime, end: datetime) -> list[str]:
    """列举 [start, end] 闭区间内、按 granularity 划分的所有周期 key（含端点）。

    - day:   每天一个 key（YYYY-MM-DD）
    - week:  每周一个 key（YYYY-Www，ISO 周）
    - month: 每月一个 key（YYYY-MM）

    起点/终点各自归入其所在的周期；步进时取该周期首日的边界，保证 key 稳定。
    """
    if start > end:
        raise BusinessError("快照起始时间不能晚于结束时间", code=400)
    periods: list[str] = []
    cur = start
    while cur <= end:
        key = _period_key(cur.strftime("%Y-%m-%dT%H:%M:%S"), granularity)
        if key not in periods:
            periods.append(key)
        if granularity == "month":
            y, m = cur.year, cur.month
            if m == 12:
                y, m = y + 1, 1
            else:
                m += 1
            cur = cur.replace(year=y, month=m, day=1)
        elif granularity == "week":
            # 跳到下一周一（_period_key 已按 ISO 周对齐，+7 天仍落在下一周期）
            cur = cur + timedelta(days=7)
        else:
            cur = cur + timedelta(days=1)
    return periods


router = APIRouter(tags=["告警管理"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "alarms", "status": "ready"}


class AlarmConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    enable_popup: bool
    enable_voice: bool
    voice_file: str | None = None
    distance_machine: int
    distance_handheld: int
    distance_badge: int
    distance_band: int


class AlarmConfigUpdate(BaseModel):
    enable_popup: bool | None = None
    enable_voice: bool | None = None
    voice_file: str | None = None
    distance_machine: int | None = None
    distance_handheld: int | None = None
    distance_badge: int | None = None
    distance_band: int | None = None


@router.get(
    "/config",
    summary="获取告警配置",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("alarm:config"))],
)
def get_config(db: Session = Depends(get_db)) -> ApiResponse:
    """返回平台告警配置（弹窗/语音/各设备间距阈值）；不存在则创建默认。"""
    cfg = db.scalars(select(AlarmConfig)).first()
    if cfg is None:
        cfg = AlarmConfig()
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return ApiResponse.success(data=AlarmConfigOut.model_validate(cfg))


@router.put(
    "/config",
    summary="更新告警配置",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("alarm:config"))],
)
def update_config(req: AlarmConfigUpdate, db: Session = Depends(get_db)) -> ApiResponse:
    """更新告警配置（部分字段即可）。"""
    cfg = db.scalars(select(AlarmConfig)).first()
    if cfg is None:
        cfg = AlarmConfig()
        db.add(cfg)
        db.flush()
    data = req.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(cfg, k, v)
    db.commit()
    db.refresh(cfg)
    return ApiResponse.success(data=AlarmConfigOut.model_validate(cfg), message="配置已更新")


class AlarmHandleRequest(BaseModel):
    handle_status: str = Field(..., description="处理状态(待处理/已处理/已忽略/已确认/已消警)")
    content: str | None = Field(None, description="处置内容")


@router.get(
    "",
    summary="告警列表",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("alarm:list"))],
)
def list_alarms(
    db: Session = Depends(get_db),
    scope=Depends(get_data_scope),
    project_id: int | None = None,
    alarm_type: str | None = None,
    handle_status: str | None = None,
    alarm_status: str | None = None,
    page: int = 1,
    size: int = 20,
) -> ApiResponse:
    """按条件分页查询告警（page/size），返回真实总数，施加部门数据隔离。"""
    total = svc_count_alarms(
        db,
        scope,
        project_id=project_id,
        alarm_type=alarm_type,
        handle_status=handle_status,
        alarm_status=alarm_status,
    )
    items = svc_list_alarms(
        db,
        scope,
        project_id=project_id,
        alarm_type=alarm_type,
        handle_status=handle_status,
        alarm_status=alarm_status,
        page=page,
        size=size,
    )
    return ApiResponse.success(data={"total": total, "items": items, "page": page, "size": size})


@router.post(
    "/{alarm_id}/handle",
    summary="处置告警",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("alarm:handle"))],
)
def handle_alarm_endpoint(
    alarm_id: int,
    req: AlarmHandleRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """处置告警；若置「已消警」，向对应设备下发消警指令（接口 2/4/6）。

    部门数据隔离：仅当前用户数据范围内可见的告警可处置。
    """
    stmt = select(Alarm).where(Alarm.id == alarm_id)
    stmt = apply_data_scope(stmt, Alarm, scope)
    if db.scalar(stmt) is None:
        raise HTTPException(status_code=404, detail="告警不存在")
    result = handle_alarm(db, alarm_id, req.handle_status, req.content)
    if result is None:
        raise HTTPException(status_code=404, detail="告警不存在")

    # 先固化业务状态（操作员处置意图），再下发设备指令，
    # 避免「指令已下发但 commit 失败导致状态回滚」的设备-数据不一致。
    db.commit()

    # 已消警 → 下发消警指令到设备（状态已落库，下发失败不影响业务一致性，仅提示）
    if (
        req.handle_status == ALARM_STATUS_CLEARED
        and result.get("device_type")
        and result.get("device_no")
    ):
        try:
            payload = protocol.build_command(result["device_type"], "alarm", {"on": False})
            mqtt_client.publish(
                _down_topic(result["device_type"], result["device_no"]),
                json.dumps(payload, ensure_ascii=False),
                qos=1,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("消警指令下发失败（处置状态已保存）：%s", exc)
            return ApiResponse.success(
                data=result, message="处置已保存，但消警指令下发失败，请检查设备连接"
            )
    return ApiResponse.success(data=result, message="处置已保存")


class AlarmMediaUpdate(BaseModel):
    urls: list[str] = Field(default_factory=list, description="媒体 URL 全量列表（整体替换）")


@router.put(
    "/{alarm_id}/media",
    summary="更新告警媒体",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("alarm:handle"))],
)
def update_alarm_media_endpoint(
    alarm_id: int,
    req: AlarmMediaUpdate,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """整体替换告警的媒体附件（图片/视频 URL 列表）。

    部门数据隔离：仅当前用户数据范围内可见的告警可更新媒体。

    前端 MediaUpload 组件维护本地列表，保存时调用本接口全量写入。
    """
    stmt = select(Alarm).where(Alarm.id == alarm_id)
    stmt = apply_data_scope(stmt, Alarm, scope)
    if db.scalar(stmt) is None:
        raise HTTPException(status_code=404, detail="告警不存在")
    result = update_alarm_media(db, alarm_id, req.urls)
    if result is None:
        raise HTTPException(status_code=404, detail="告警不存在")
    db.commit()  # service 不提交，端点统一提交（#7）
    return ApiResponse.success(data={"id": alarm_id, "media_urls": result})


# ---------------------------------------------------------------------------
# 告警报表 / 导出
# ---------------------------------------------------------------------------


def _filters_desc(
    start: str | None,
    end: str | None,
    project_id: int | None,
    alarm_type: str | None,
    handle_status: str | None,
    alarm_level: str | None,
) -> str:
    parts: list[str] = []
    if start or end:
        parts.append(f"时间 {start or '不限'} ~ {end or '不限'}")
    if project_id is not None:
        parts.append(f"项目#{project_id}")
    if alarm_type:
        parts.append(f"类型={alarm_type}")
    if handle_status:
        parts.append(f"处置={handle_status}")
    if alarm_level:
        parts.append(f"级别={alarm_level}")
    return "；".join(parts) if parts else "全部"


@router.get(
    "/report",
    summary="告警报表（聚合 + 明细预览）",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("alarm:list"))],
)
def alarm_report(
    db: Session = Depends(get_db),
    scope=Depends(get_data_scope),
    start: str | None = Query(None, description="起始时间 ISO"),
    end: str | None = Query(None, description="结束时间 ISO"),
    project_id: int | None = None,
    alarm_type: str | None = None,
    handle_status: str | None = None,
    alarm_level: str | None = None,
    granularity: str = Query("day", description="聚合粒度：day|week|month"),
    preview_limit: int = Query(50, description="明细预览条数"),
    summary_only: bool = Query(
        False, description="仅返回聚合统计（live 趋势联动用，省去明细预览）"
    ),
) -> ApiResponse:
    """返回聚合统计 + 明细预览（前端报表页用）。数据范围按部门隔离。

    granularity 控制 by_period 的聚合粒度（day/week/month）；by_day 始终为按天分布。
    summary_only=true 时只返回 summary + filters_desc（不构建明细预览），
    供主视图「随筛选联动」的轻量趋势刷新使用。
    """
    if granularity not in ("day", "week", "month"):
        raise BusinessError("granularity 仅支持 day|week|month", code=400)
    rows = query_alarms_for_report(
        db,
        scope,
        start=_parse_dt(start),
        end=_parse_dt(end),
        project_id=project_id,
        alarm_type=alarm_type,
        handle_status=handle_status,
        alarm_level=alarm_level,
    )
    summary = aggregate_alarms(rows, granularity=granularity)
    return ApiResponse.success(
        data={
            "summary": summary,
            "items": [] if summary_only else rows[:preview_limit],
            "preview_count": 0 if summary_only else min(preview_limit, len(rows)),
            "filters_desc": _filters_desc(
                start, end, project_id, alarm_type, handle_status, alarm_level
            ),
        }
    )


@router.get(
    "/daily",
    summary="某日告警明细（报表柱状图下钻）",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("alarm:list"))],
)
def alarm_daily(
    db: Session = Depends(get_db),
    scope=Depends(get_data_scope),
    date: str = Query(..., description="日期 YYYY-MM-DD"),
    project_id: int | None = None,
    alarm_type: str | None = None,
    handle_status: str | None = None,
    alarm_level: str | None = None,
) -> ApiResponse:
    """返回指定日期（且满足其余筛选条件）的告警明细，供「按天趋势柱状图」下钻。

    日期边界为当日 [00:00:00, 23:59:59.999999]；其余筛选条件与 /report 一致，
    数据范围同样按部门隔离。
    """
    start, end = _parse_date(date)
    rows = query_alarms_for_report(
        db,
        scope,
        start=start,
        end=end,
        project_id=project_id,
        alarm_type=alarm_type,
        handle_status=handle_status,
        alarm_level=alarm_level,
    )
    return ApiResponse.success(
        data={
            "total": len(rows),
            "items": rows,
            "date": date,
            "filters_desc": _filters_desc(
                date + "T00:00:00",
                date + "T23:59:59",
                project_id,
                alarm_type,
                handle_status,
                alarm_level,
            ),
        }
    )


@router.get(
    "/period",
    summary="按周期(天/周/月)聚合下钻明细",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("alarm:list"))],
)
def alarm_period(
    db: Session = Depends(get_db),
    scope=Depends(get_data_scope),
    granularity: str = Query("day", description="聚合粒度：day|week|month"),
    period: str = Query(..., description="周期值：day=YYYY-MM-DD / week=YYYY-Www / month=YYYY-MM"),
    project_id: int | None = None,
    alarm_type: str | None = None,
    handle_status: str | None = None,
    alarm_level: str | None = None,
) -> ApiResponse:
    """返回指定周期（且满足其余筛选条件）的告警明细，供趋势图按粒度下钻。

    周期边界由 granularity + period 推导（见 _parse_period），其余筛选条件与
    /report 一致，数据范围同样按部门隔离。
    """
    if granularity not in ("day", "week", "month"):
        raise BusinessError("granularity 仅支持 day|week|month", code=400)
    start, end = _parse_period(granularity, period)
    rows = query_alarms_for_report(
        db,
        scope,
        start=start,
        end=end,
        project_id=project_id,
        alarm_type=alarm_type,
        handle_status=handle_status,
        alarm_level=alarm_level,
    )
    return ApiResponse.success(
        data={
            "granularity": granularity,
            "period": period,
            "total": len(rows),
            "items": rows,
            "filters_desc": _filters_desc(
                f"{granularity}:{period}",
                None,
                project_id,
                alarm_type,
                handle_status,
                alarm_level,
            ),
        }
    )


def _compute_snapshot(
    db: Session,
    scope: "DataScope",
    gran: str,
    p_start: datetime,
    p_end: datetime,
    start_raw: str | None,
    end_raw: str | None,
    project_id: int | None = None,
    alarm_type: str | None = None,
    handle_status: str | None = None,
    alarm_level: str | None = None,
) -> tuple[list[str], dict[str, list], dict, dict, dict]:
    """历史快照的通用计算：返回 (period_keys, period_rows, summary, project_names, meta)。

    导出（Excel/PDF）与 JSON 预览共用同一份计算结果，保证「预览即所见导出的内容」。

    性能优化（#6）：原先对 period_keys 中**每个周期各发一次** query_alarms_for_report
    （周×12 月 ≈ 52 次查询）。改为**一次查出整窗**、再在 Python 内按 _period_key 分桶，
    将 N 次查询降为 1 次。

    正确性注意：
    - 单次查询窗口扩展到「首周期完整起点 → 末周期完整终点」(_parse_period 的 .999999 微秒边界)，
      等价于逐周期 [b_start,b_end] 的并集，避免直接用用户传入的 p_start/p_end 漏掉周期首尾告警。
    - limit=None 不截断，保证跨整窗汇总与逐周期累加完全一致（原逐周期各 5000 上限会丢数据）。
    - period_rows 以 period_keys 为全量键初始化空桶，确保「无告警的空周期」仍出现在输出中。
    - 分桶所用 alarm_time 字符串与 aggregate_alarms 内部 _period_key 同源（均来自 to_alarm_out
      的 isoformat），周期归属与旧逻辑逐字节一致。
    """
    period_keys = _enumerate_periods(gran, p_start, p_end)
    period_rows: dict[str, list] = {pk: [] for pk in period_keys}
    if period_keys:
        # 整窗边界 = 首周期起点 ∪ 末周期终点（含微秒），覆盖所有逐周期查询的并集
        win_start, _ = _parse_period(gran, period_keys[0])
        _, win_end = _parse_period(gran, period_keys[-1])
        all_rows = query_alarms_for_report(
            db,
            scope,
            start=win_start,
            end=win_end,
            project_id=project_id,
            alarm_type=alarm_type,
            handle_status=handle_status,
            alarm_level=alarm_level,
            limit=None,
        )
        for r in all_rows:
            k = _period_key(r.get("alarm_time"), gran)
            period_rows.setdefault(k, []).append(r)
    else:
        all_rows = []
    summary = aggregate_alarms(all_rows, granularity=gran)
    # 项目名映射（受部门数据隔离），供快照按项目分组 / 项目汇总使用
    proj_stmt = apply_data_scope(
        select(Project.id, Project.name).where(Project.is_deleted.is_(False)),
        Project,
        scope,
    )
    project_names = {pid: pname for pid, pname in db.execute(proj_stmt).all()}
    meta = {
        "title": "涉铁工程告警历史快照",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "filters_desc": _filters_desc(
            start_raw, end_raw, project_id, alarm_type, handle_status, alarm_level
        ),
    }
    return period_keys, period_rows, summary, project_names, meta


@router.get(
    "/export",
    summary="导出告警报表（Excel/PDF）",
    dependencies=[Depends(require_permissions("alarm:list"))],
)
def alarm_export(
    db: Session = Depends(get_db),
    scope=Depends(get_data_scope),
    fmt: str = Query("excel", description="导出格式：excel | pdf"),
    start: str | None = Query(None, description="起始时间 ISO"),
    end: str | None = Query(None, description="结束时间 ISO"),
    granularity: str | None = Query(
        None, description="周期粒度：day|week|month（与 period/snapshot 搭配）"
    ),
    period: str | None = Query(
        None, description="周期值：day=YYYY-MM-DD / week=YYYY-Www / month=YYYY-MM（单周期一键导出）"
    ),
    snapshot: bool = Query(
        False,
        description="历史快照模式：按 granularity 把 [start,end] 拆成多个周期，每个周期单独成表",
    ),
    project_id: int | None = None,
    alarm_type: str | None = None,
    handle_status: str | None = None,
    alarm_level: str | None = None,
) -> StreamingResponse:
    """流式下载告警报表文件。fmt=excel 返回 xlsx，fmt=pdf 返回 pdf。

    三种模式（优先级 period > snapshot > 范围）：
    1. period 存在 → 用 (granularity, period) 推导边界，单周期一键导出整周/整月；
    2. snapshot=true → 按 granularity 把 [start,end] 拆成多个周期，构建多 sheet 快照
       （概览 + 每周期明细 + 合并明细），一个文件看遍跨周/月历史；
    3. 默认 → 沿用手填 start/end 范围，单表导出。
    """
    fmt = (fmt or "excel").lower()
    if fmt not in ("excel", "xlsx", "pdf"):
        raise BusinessError("不支持的导出格式（excel|pdf）", code=400)

    # ---- 模式 2：跨周期历史快照 ----
    if snapshot and not period:
        gran = (granularity or "week").lower()
        if gran not in ("day", "week", "month"):
            raise BusinessError("快照粒度仅支持 day|week|month", code=400)
        p_start = _parse_dt(start)
        p_end = _parse_dt(end)
        if p_start is None or p_end is None:
            raise BusinessError("历史快照导出需同时指定 start 与 end 时间范围", code=400)
        period_keys, period_rows, summary, project_names, meta = _compute_snapshot(
            db,
            scope,
            gran,
            p_start,
            p_end,
            start,
            end,
            project_id=project_id,
            alarm_type=alarm_type,
            handle_status=handle_status,
            alarm_level=alarm_level,
        )
        tag = f"{gran}_{(start or '')[:10]}_{(end or '')[:10]}"
        if fmt == "pdf":
            content = build_pdf_snapshot(
                gran, period_keys, period_rows, summary, meta, project_names
            )
            media_type = "application/pdf"
            filename = f"alarm_snapshot_{tag}.pdf"
        else:
            content = build_excel_snapshot(
                gran, period_keys, period_rows, summary, meta, project_names
            )
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            filename = f"alarm_snapshot_{tag}.xlsx"
        disposition = f"attachment; filename={filename}; filename*=UTF-8''{quote(filename)}"
        return StreamingResponse(
            iter([content]),
            media_type=media_type,
            headers={"Content-Disposition": disposition},
        )

    # ---- 模式 1：单周期联动 ----
    filters_start, filters_end = start, end
    if period:
        gran = (granularity or "day").lower()
        if gran not in ("day", "week", "month"):
            raise BusinessError("granularity 仅支持 day|week|month", code=400)
        p_start, p_end = _parse_period(gran, period)
        filters_start = p_start.strftime("%Y-%m-%dT%H:%M:%S")
        filters_end = p_end.strftime("%Y-%m-%dT%H:%M:%S")
        rows = query_alarms_for_report(
            db,
            scope,
            start=p_start,
            end=p_end,
            project_id=project_id,
            alarm_type=alarm_type,
            handle_status=handle_status,
            alarm_level=alarm_level,
        )
    else:
        # ---- 模式 3：默认范围 ----
        rows = query_alarms_for_report(
            db,
            scope,
            start=_parse_dt(start),
            end=_parse_dt(end),
            project_id=project_id,
            alarm_type=alarm_type,
            handle_status=handle_status,
            alarm_level=alarm_level,
        )
    summary = aggregate_alarms(rows)
    meta = {
        "title": "涉铁工程告警报表",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "filters_desc": _filters_desc(
            filters_start,
            filters_end,
            project_id,
            alarm_type,
            handle_status,
            alarm_level,
        ),
    }
    # 文件名：周期导出用 period 标识（如 2026-W29 / 2026-07），否则用时间戳
    tag = period if period else datetime.now().strftime("%Y%m%d_%H%M%S")

    if fmt == "pdf":
        content = build_pdf(rows, summary, meta)
        media_type = "application/pdf"
        filename = f"alarm_report_{tag}.pdf"
    else:
        content = build_excel(rows, summary, meta)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"alarm_report_{tag}.xlsx"

    # RFC 5987：支持含非 ASCII 的下载名（此处为纯 ASCII，兼容即可）
    disposition = f"attachment; filename={filename}; filename*=UTF-8''{quote(filename)}"
    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


@router.get(
    "/snapshot/preview",
    summary="历史快照预览（JSON）",
    dependencies=[Depends(require_permissions("alarm:list"))],
)
def alarm_snapshot_preview(
    db: Session = Depends(get_db),
    scope=Depends(get_data_scope),
    granularity: str = Query("week", description="周期粒度：day|week|month"),
    start: str | None = Query(None, description="起始时间 ISO"),
    end: str | None = Query(None, description="结束时间 ISO"),
    project_id: int | None = None,
    alarm_type: str | None = None,
    handle_status: str | None = None,
    alarm_level: str | None = None,
) -> "ApiResponse":
    """历史快照预览：返回概览 + 各周期分布 + 按项目汇总 的 JSON，与 Excel/PDF 快照同源。

    前端报表弹窗据此渲染「快照/项目汇总」预览，确认无误后再调用 /export 下载。
    """
    gran = (granularity or "week").lower()
    if gran not in ("day", "week", "month"):
        raise BusinessError("快照粒度仅支持 day|week|month", code=400)
    p_start = _parse_dt(start)
    p_end = _parse_dt(end)
    if p_start is None or p_end is None:
        raise BusinessError("历史快照预览需同时指定 start 与 end 时间范围", code=400)
    period_keys, period_rows, summary, project_names, meta = _compute_snapshot(
        db,
        scope,
        gran,
        p_start,
        p_end,
        start,
        end,
        project_id=project_id,
        alarm_type=alarm_type,
        handle_status=handle_status,
        alarm_level=alarm_level,
    )
    payload = build_snapshot_payload(gran, period_keys, period_rows, summary, meta, project_names)
    return ApiResponse(data=payload)

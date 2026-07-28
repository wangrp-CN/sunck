"""闭环效能运营报告生成器（导出基座复用）。

把 ``app.api.v1.dashboard.effectiveness_export`` 内联的报告拼装逻辑下沉为可复用函数
``generate_effectiveness_report``，供两类调用方共用：

- 前端「按项目维度导出」端点（``GET /v1/dashboard/effectiveness/export``）；
- 定期订阅推送（``app.service.report_subscription``）：到点生成报告并经通知中心下发。

返回 ``(content: bytes, filename: str, media_type: str)``，调用方自行决定
StreamingResponse 直出 或 落库/触达。数据范围由传入 ``scope`` 决定。
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.core.data_scope import DataScope
from app.core.exceptions import BusinessError
from app.core.scoring import (
    project_risk_score,  # noqa: F401  （确保评分口径已注册，保持与端点一致）
)
from app.service import report_common
from app.service.effectiveness_service import collect_project_series, compute_effectiveness
from app.service.report_common import build_simple_excel, build_simple_pdf


def generate_effectiveness_report(
    db: Session,
    scope: DataScope,
    *,
    days: int = 30,
    fmt: str = "excel",
    project_id: int | None = None,
) -> tuple[bytes, str, str]:
    """生成按项目维度的闭环效能运营报告（Excel / PDF）。

    Args:
        db: 数据库会话。
        scope: 数据范围（部门隔离）。
        days: 效能统计窗口（天）。
        fmt: ``excel`` | ``pdf``。
        project_id: 聚焦项目（仅影响标题，明细仍含全量项目）。

    Returns:
        ``(content_bytes, filename, media_type)``。
    """
    fmt = (fmt or "excel").lower()
    if fmt not in ("excel", "pdf"):
        raise BusinessError("不支持的导出格式（excel|pdf）", code=400)

    data = compute_effectiveness(db, scope, days=days, project_id=project_id)

    # 各项目历史时间序列（导出报告生成复合迷你趋势图用）
    project_ids = [p["project_id"] for p in data["by_project"]]
    project_series = (
        collect_project_series(db, scope, days=days, project_ids=project_ids) if project_ids else {}
    )

    # 明细行：各项目同构指标（by_project 已按风险分降序）
    rows: list[dict] = []
    for p in data["by_project"]:
        rows.append(
            {
                "project_id": p["project_id"],
                "project_name": p["project_name"],
                "risk_level": p["risk_level"],
                "risk_index": p["risk_index"],
                "storm_rate": p["storm"]["rate_pct"],
                "suppressed": p["storm"]["suppressed"],
                "mttr_hours": p["mttr"]["avg_hours"],
                "resolution_rate": p["mttr"]["resolution_rate_pct"],
                "sla_rate": p["dispatch_sla"]["sla_rate_pct"],
                "avg_cycle_hours": p["dispatch_sla"]["avg_cycle_hours"],
                "closure_rate": p["hazard"]["closure_rate_pct"],
                "on_time_rate": p["hazard"]["on_time_rate_pct"],
                "anomaly_share": p["anomaly"]["share_pct"],
                "alarms": p["storm"]["alarms"],
                "d_closed": p["dispatch_sla"]["closed"],
                "h_closed": p["hazard"]["closed"],
                "h_total": p["hazard"]["total"],
                "corr_dispatch": p["anomaly"]["correlation_dispatches"],
            }
        )

    columns = [
        ("project_name", "项目", 22, 40),
        ("risk_level", "风险等级", 10, 18),
        ("risk_index", "风险分", 10, 18),
        ("trend", "历史趋势", 28, 80),  # 复合迷你图（5 指标一条龙）
        ("storm_rate", "风暴抑制率%", 13, 20),
        ("suppressed", "压掉同源重复", 14, 18),
        ("mttr_hours", "平均处置(h)", 13, 18),
        ("resolution_rate", "处置率%", 12, 16),
        ("sla_rate", "派单SLA%", 11, 16),
        ("avg_cycle_hours", "闭环均(h)", 12, 16),
        ("closure_rate", "隐患闭环率%", 13, 18),
        ("on_time_rate", "按期销号%", 12, 16),
        ("anomaly_share", "异常占比%", 12, 16),
        ("alarms", "告警总数", 11, 16),
        ("d_closed", "派单闭环", 11, 16),
        ("h_closed", "隐患销号", 11, 16),
        ("h_total", "隐患总数", 11, 16),
        ("corr_dispatch", "共因派单", 11, 16),
    ]

    # 历史趋势列：每行调用 PNG 生成器（per-project 5 指标复合迷你图）
    def _trend_png(row: dict) -> bytes:
        pid = row.get("project_id")
        ser = project_series.get(pid) if pid is not None else None
        if not ser:
            return b""
        return report_common.render_composite_sparkline_png(ser)

    image_columns = [("trend", "历史趋势", _trend_png)]

    def _delta(m: dict) -> str:
        d = m.get("trend", {}).get("delta_pct")
        return f"{d:+.1f}%" if d is not None else "无对比"

    summary_blocks = [
        (
            "核心指标（当前窗口 vs 上一周期）",
            [
                ("告警风暴抑制率", f"{data['storm']['rate_pct']}% (Δ{_delta(data['storm'])})"),
                ("告警平均处置时长", f"{data['mttr']['avg_hours']}h (Δ{_delta(data['mttr'])})"),
                (
                    "派单SLA达成率",
                    f"{data['dispatch_sla']['sla_rate_pct']}% (Δ{_delta(data['dispatch_sla'])})",
                ),
                (
                    "隐患治理闭环率",
                    f"{data['hazard']['closure_rate_pct']}% (Δ{_delta(data['hazard'])})",
                ),
                (
                    "异常引擎告警占比",
                    f"{data['anomaly']['share_pct']}% (Δ{_delta(data['anomaly'])})",
                ),
            ],
        ),
    ]

    focus_name = None
    if project_id is not None:
        focus_name = next(
            (p["project_name"] for p in data["by_project"] if p["project_id"] == project_id),
            None,
        )
    filters_desc = f"窗口：近{days}天（{data['range_start'][:10]} ~ {data['range_end'][:10]}）" + (
        f" · 聚焦项目：{focus_name}" if focus_name else ""
    )
    meta = {
        "title": "闭环效能运营报告（按项目维度）",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "filters_desc": filters_desc,
    }

    if fmt == "pdf":
        content = build_simple_pdf(columns, rows, meta, summary_blocks, image_columns=image_columns)
        media_type = "application/pdf"
        filename = f"效能运营报告_{days}d.pdf"
    else:
        content = build_simple_excel(
            columns, rows, meta, summary_blocks, image_columns=image_columns
        )
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"效能运营报告_{days}d.xlsx"

    return content, filename, media_type


def disposition_header(filename: str, ascii_fallback: str) -> str:
    """构造 RFC5987 Content-Disposition（ASCII 回退 + UTF-8 真名，兼容老客户端）。"""
    return f"attachment; filename={ascii_fallback}; filename*=UTF-8''{quote(filename)}"

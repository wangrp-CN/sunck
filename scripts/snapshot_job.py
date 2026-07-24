#!/usr/bin/env python
"""定时快照任务（智能核心 v2）：聚合风险/健康分落库 risk_health_snapshot。

用法：
  PYTHONPATH=/opt/rail_monitor .venv/bin/python scripts/snapshot_job.py
  PYTHONPATH=/opt/rail_monitor .venv/bin/python scripts/snapshot_job.py --hours 24 --days 7

配合 systemd timer（deploy/scripts/rail-monitor-snapshot.{service,timer}）每日定时执行。
聚合口径与 devices/health、dashboard/project-compare 端点完全一致（见 app/service/metrics_snapshot.py）。
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

# 抑制 SQLAlchemy 引擎回声，只保留结论
for _nm in ("sqlalchemy", "sqlalchemy.engine", "sqlalchemy.engine.Engine", "sqlalchemy.pool"):
    logging.getLogger(_nm).setLevel(logging.WARNING)

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from app.core.database import SessionLocal
from app.service import metrics_snapshot as svc
from app.service import risk_alert as alert_svc
from app.service import alarm_correlation as corr_svc
from app.config import settings


def main() -> None:
    ap = argparse.ArgumentParser(description="风险/健康分时序快照 + 关联计算")
    ap.add_argument("--hours", type=int, default=24, help="设备健康统计窗口(小时)")
    ap.add_argument("--days", type=int, default=7, help="项目风险统计窗口(天)")
    ap.add_argument(
        "--corr-window",
        type=int,
        default=settings.correlation_window_hours,
        help="跨设备关联回溯窗口(小时)",
    )
    ap.add_argument(
        "--corr-gap",
        type=int,
        default=settings.correlation_gap_minutes,
        help="跨设备关联时间窗聚类间隔(分钟)",
    )
    args = ap.parse_args()

    db = SessionLocal()
    try:
        res = svc.run_snapshot(db, hours=args.hours, days=args.days)
        print(f"[snapshot] {datetime.now(timezone.utc).isoformat()} -> {res}", flush=True)

        # 阈值预警（智能核心 v2）：评估越阈 + 基于 RiskAlertState 去重下发站内信。
        breaches = alert_svc.evaluate_risk_alerts(db)
        print(f"[snapshot] risk breaches={len(breaches)}", flush=True)
        sent = alert_svc.alert_newly_breached(db)
        if sent:
            print(f"[snapshot] risk_alert notifications sent={sent}", flush=True)

        # 跨设备根因关联（#77）：全量重算事件组派生表。
        corr = corr_svc.run_correlations(
            db, window_hours=args.corr_window, cluster_gap_minutes=args.corr_gap
        )
        print(
            f"[snapshot] correlations groups={corr['groups']} "
            f"cross_device={corr['cross_device_groups']}",
            flush=True,
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()

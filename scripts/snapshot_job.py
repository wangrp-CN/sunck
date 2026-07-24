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


def main() -> None:
    ap = argparse.ArgumentParser(description="风险/健康分时序快照")
    ap.add_argument("--hours", type=int, default=24, help="设备健康统计窗口(小时)")
    ap.add_argument("--days", type=int, default=7, help="项目风险统计窗口(天)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        res = svc.run_snapshot(db, hours=args.hours, days=args.days)
        print(f"[snapshot] {datetime.now(timezone.utc).isoformat()} -> {res}", flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()

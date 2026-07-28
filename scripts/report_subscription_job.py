#!/usr/bin/env python
"""定期订阅推送任务（模块①·报告与触达增强）。

每小时由 systemd timer 触发一次：扫描全部启用订阅，对「当前时刻到点」者生成效能运营
报告并经通知中心触达（in_app 真实，sms/voice 预留）。因订阅记录 ``last_run_at`` 已记
本周期运行时刻，天然幂等，不会同周期重复下发——故可放心每小时调用。

用法：
  PYTHONPATH=/opt/rail_monitor .venv/bin/python scripts/report_subscription_job.py

配合 deploy/scripts/rail-monitor-subscription.{service,timer}（每小时 :05 运行）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

# 抑制 SQLAlchemy 引擎回声
for _nm in ("sqlalchemy", "sqlalchemy.engine", "sqlalchemy.engine.Engine", "sqlalchemy.pool"):
    logging.getLogger(_nm).setLevel(logging.WARNING)

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from app.core.database import SessionLocal
from app.service import report_subscription as sub_svc


def main() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        results = sub_svc.run_due_subscriptions(db, now)
        ok = sum(1 for r in results if r.get("status") == "ok")
        failed = sum(1 for r in results if r.get("status") == "failed")
        print(
            f"[subscription] {now.isoformat()} -> due={len(results)} ok={ok} failed={failed}",
            flush=True,
        )
        for r in results:
            if r.get("status") == "failed":
                print(f"[subscription] FAILED id={r.get('id')} {r.get('error')}", flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()

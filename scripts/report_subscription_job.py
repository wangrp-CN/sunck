#!/usr/bin/env python
"""定期订阅推送任务（模块①·报告与触达增强）。

每小时由 systemd timer 触发一次：扫描全部启用订阅，对「当前时刻到点」者生成效能运营
报告并经通知中心触达（in_app 真实，sms/voice 预留）。因订阅记录 ``last_run_at`` 已记
本周期运行时刻，天然幂等，不会同周期重复下发——故可放心每小时调用。

同时承担「设备指令下发闭环」的周期重试：对超时未回执或失败且未达上限的指令自动重发，
直至达到 ``command_max_retries``（详见 app.service.command_service.retry_stale_commands）。

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

from app.core.database import SessionLocal  # noqa: E402
from app.service import alarm_policy_service  # noqa: E402
from app.service import command_service  # noqa: E402
from app.service import report_subscription as sub_svc  # noqa: E402


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

        # 设备指令下发闭环：周期重试超时未回执/失败的指令
        retry = command_service.retry_stale_commands(db, now=now)
        if retry["total"]:
            print(
                f"[command] {now.isoformat()} -> stale={retry['total']} "
                f"retried={retry['retried']} exhausted={retry['exhausted']}",
                flush=True,
            )

        # 告警治理（🅱 M4）：超时未处理告警按策略升级级别 + 重新通知（含当班人）
        esc = alarm_policy_service.run_escalations(db, now=now)
        if esc["escalated"]:
            print(
                f"[escalation] {now.isoformat()} -> scanned={esc['scanned']} "
                f"escalated={esc['escalated']} ids={esc['alarm_ids']}",
                flush=True,
            )
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()

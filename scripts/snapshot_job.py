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

from app.config import settings
from app.core.database import SessionLocal
from app.service import alarm_correlation as corr_svc
from app.service import anomaly_service as anomaly_svc
from app.service import backtest_service as bt_svc
from app.service import feature_provider as feat_svc
from app.service import forecast_service as forecast_svc
from app.service import metrics_snapshot as svc
from app.service import risk_alert as alert_svc


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

        # 趋势异常检测（#81 扩展）：检测四类序列异常 → 落 trend_anomaly 告警
        # （进既有告警流 + 可在告警管理页「一键派单」接入根因派单闭环）。
        anoms = anomaly_svc.run_anomaly_detection(db)
        print(f"[snapshot] anomaly alarms created={anoms['created']}", flush=True)

        # 外部特征回填（预测特征工程：突破单序列）。保证近 N 天外部特征已落库，
        # 供 hw_feat_v1 残差融合校正使用。独立 try 保护，避免影响关键快照。
        try:
            filled = feat_svc.ensure_external_features(db, days=settings.feature_backfill_days)
            print(f"[snapshot] external features backfilled={filled}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[snapshot] external feature backfill skipped: {exc}", flush=True)

        # 风险预测（Phase 5 M1）：对每个项目的 risk_index 日序列做 OLS 趋势
        # 外推，upsert 落 forecast 表（供预测列表 / 预测性预警 / 驾驶舱预测卡）。
        fc = forecast_svc.run_forecasts(db)
        print(
            f"[snapshot] forecasts computed={fc['computed']} skipped={fc['skipped']}",
            flush=True,
        )

        # 预测性预警回灌（Phase 5 M3）：越阈预测自动生成 predictive_alert 告警，
        # 进既有告警流（站内信通知 + 告警管理页一键派单闭环）。
        alerts = forecast_svc.run_predictive_alerts(db)
        print(f"[snapshot] predictive alerts created={alerts['created']}", flush=True)

        # A/B 回测（预测模型升级）：walk-forward 回测落 forecast_backtest，
        # 供 A/B 命中率报表对比各模型（ols_v1 / hw_v1）。独立 try 保护，避免影响关键快照。
        try:
            bt = bt_svc.run_backtest(
                db, days=settings.forecast_backtest_days, horizon=settings.forecast_horizon_days
            )
            print(f"[snapshot] backtest rows={bt['rows']} anchors={bt['anchors']}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[snapshot] backtest skipped due to error: {exc}", flush=True)

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()

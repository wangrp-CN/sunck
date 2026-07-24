"""评分权重标定回测工具（核心智能算法调优的配套标定器）。

用途：
  1) 实时回测：对当前数据库跑设备健康分 / 项目风险分，打印分档分布与统计，
     帮你在真实数据上直观看到当前权重产生的分档是否合理。
  2) 权重敏感性：用 --weights w.json 覆盖 scoring 模块常量后重跑，对比分档迁移，
     用于确定权重该往哪调。
  3) 场景矩阵（--matrix）：枚举典型场景 → 分档映射，无需真实数据即可看清边界。
  4) 参数扫描（--sweep）：对关键参数做一维扫描，观察分档随参数变化是否平滑。

用法（在 rail_monitor 项目根目录，用项目 venv 运行）：
  python scripts/backtest_scoring.py                 # 实时回测（默认窗口 24h / 7d）
  python scripts/backtest_scoring.py --hours 24 --days 7
  python scripts/backtest_scoring.py --weights weights.json   # 覆盖权重后回测
  python scripts/backtest_scoring.py --matrix        # 场景→分档映射矩阵
  python scripts/backtest_scoring.py --sweep         # 关键参数敏感性扫描

weights.json 示例（键名见本文件 WEIGHT_KEYS；只写要覆盖的项）：
  {
    "risk_normalize_k": 30,
    "alarm_severity_weight": {"严重": 4.0, "警告": 2.0, "提示": 1.0},
    "health_penalty_cap": 50
  }

注意：权重覆盖通过临时改写 app.core.scoring 模块级常量实现，只在本次进程内生效。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from collections import Counter
from datetime import datetime, timedelta, timezone

# 抑制 SQLAlchemy 引擎回声日志，只保留回测结论
for _nm in ("sqlalchemy", "sqlalchemy.engine", "sqlalchemy.engine.Engine", "sqlalchemy.pool"):
    logging.getLogger(_nm).setLevel(logging.WARNING)

# 兼容无 .env 自动加载环境：显式 load_dotenv（失败则依赖已注入的环境变量）
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from sqlalchemy import func, select

from app.config import settings
from app.core.database import SessionLocal
from app.core.scoring import (
    device_health_level,
    device_health_score,
    project_risk_score,
)
from app.model.alarm import Alarm
from app.model.device import AntiIntrusionDevice, LocateDevice, TrainApproachDevice
from app.model.hazard import Hazard
from app.model.project import Project
from app.model.realtime import DeviceLocation

# 权重覆盖键 → scoring 模块常量名
WEIGHT_KEYS = {
    "health_online_fresh": "HEALTH_ONLINE_FRESH",
    "health_online_stale": "HEALTH_ONLINE_STALE",
    "health_offline": "HEALTH_OFFLINE",
    "health_report_bonus": "HEALTH_REPORT_BONUS",
    "health_penalty_cap": "HEALTH_ALARM_PENALTY_CAP",
    "alarm_severity_weight": "ALARM_SEVERITY_WEIGHT",
    "hazard_level_weight": "HAZARD_LEVEL_WEIGHT",
    "risk_unhandled_mult": "RISK_UNHANDLED_MULT",
    "risk_overdue_hazard": "RISK_OVERDUE_HAZARD",
    "risk_open_hazard": "RISK_OPEN_HAZARD",
    "risk_normalize_k": "RISK_NORMALIZE_K",
    "risk_level_high": "RISK_LEVEL_HIGH",
    "risk_level_mid": "RISK_LEVEL_MID",
    "health_level_good": "HEALTH_LEVEL_GOOD",
    "health_level_fair": "HEALTH_LEVEL_FAIR",
    "health_level_mid": "HEALTH_LEVEL_MID",
}

DEVICE_MODELS = [AntiIntrusionDevice, LocateDevice, TrainApproachDevice]
HAZARD_OPEN = ["待整改", "整改中", "待复核"]  # 未销号（含已驳回不计入存量）


def apply_weights(override: dict) -> None:
    """把覆盖字典写到 scoring 模块常量上（仅本次进程生效）。"""
    import app.core.scoring as sc

    for k, v in override.items():
        if k not in WEIGHT_KEYS:
            raise SystemExit(f"未知权重键: {k}（可用: {', '.join(WEIGHT_KEYS)}）")
        setattr(sc, WEIGHT_KEYS[k], v)


# ---------------------------------------------------------------------------
# 实时回测
# ---------------------------------------------------------------------------
def live_health(db, hours: int):
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    threshold = settings.online_threshold_seconds

    device_nos: list[str] = []
    for m in DEVICE_MODELS:
        rows = db.execute(select(m.device_no).where(m.is_deleted.is_(False))).all()
        device_nos.extend(r[0] for r in rows)
    if not device_nos:
        return []

    last_rows = db.execute(
        select(DeviceLocation.device_no, func.max(DeviceLocation.report_time))
        .where(DeviceLocation.device_no.in_(device_nos))
        .group_by(DeviceLocation.device_no)
    ).all()
    last_seen = {r[0]: r[1] for r in last_rows}

    alarm_rows = db.execute(
        select(Alarm.device_no, Alarm.alarm_level, func.count(Alarm.id))
        .where(Alarm.device_no.in_(device_nos), Alarm.alarm_time >= since)
        .group_by(Alarm.device_no, Alarm.alarm_level)
    ).all()
    alarm_sev: dict[str, dict[str, int]] = {}
    for no, lvl, cnt in alarm_rows:
        alarm_sev.setdefault(no, {}).setdefault(lvl or "提示", cnt)

    out = []
    for no in device_nos:
        last = last_seen.get(no)
        age = (now - last).total_seconds() if last is not None else None
        if age is None:
            state = "offline"
        elif age <= threshold:
            state = "fresh"
        elif age <= 2 * threshold:
            state = "stale"
        else:
            state = "offline"
        sev = alarm_sev.get(no, {})
        score = device_health_score(
            online_state=state, reported=bool(sev), alarm_severity_counts=sev
        )
        out.append((no, state, score, device_health_level(score)))
    return out


def live_risk(db, days: int):
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    projects = db.scalars(select(Project).where(Project.is_deleted.is_(False))).all()
    if not projects:
        return []
    pids = [p.id for p in projects]

    unhandled_rows = db.execute(
        select(Alarm.project_id, Alarm.alarm_level, func.count(Alarm.id))
        .where(
            Alarm.project_id.in_(pids),
            Alarm.alarm_time >= since,
            Alarm.handle_status == "待处理",
        )
        .group_by(Alarm.project_id, Alarm.alarm_level)
    ).all()
    unhandled_by_level: dict[int, dict[str, int]] = {}
    for pid, lvl, cnt in unhandled_rows:
        unhandled_by_level.setdefault(pid, {}).setdefault(lvl or "提示", cnt)

    overdue_rows = db.execute(
        select(Hazard.project_id, Hazard.level, func.count(Hazard.id))
        .where(
            Hazard.project_id.in_(pids),
            Hazard.is_deleted.is_(False),
            Hazard.status.in_(HAZARD_OPEN),
            Hazard.due_at.is_not(None),
            Hazard.due_at < now,
        )
        .group_by(Hazard.project_id, Hazard.level)
    ).all()
    overdue_by_level: dict[int, dict[str, int]] = {}
    for pid, lvl, cnt in overdue_rows:
        overdue_by_level.setdefault(pid, {}).setdefault(lvl or "一般", cnt)

    open_rows = db.execute(
        select(Hazard.project_id, func.count(Hazard.id))
        .where(
            Hazard.project_id.in_(pids),
            Hazard.is_deleted.is_(False),
            Hazard.status.in_(HAZARD_OPEN),
        )
        .group_by(Hazard.project_id)
    ).all()
    open_by_pid = {pid: cnt for pid, cnt in open_rows}

    out = []
    for p in projects:
        raw, idx, level = project_risk_score(
            unhandled_by_level=unhandled_by_level.get(p.id, {}),
            overdue_by_level=overdue_by_level.get(p.id, {}),
            open_hazards=open_by_pid.get(p.id, 0),
        )
        out.append((p.id, p.name, raw, idx, level))
    return out


def _bar(label: str, count: int, total: int, width: int = 32) -> str:
    filled = int(round(width * count / total)) if total else 0
    return f"{label:<6} {count:>5} {count/total:>7.1%} | {'█' * filled}"


def print_live(health, risk):
    print("\n==================== 设备健康分（实时） ====================")
    if not health:
        print("（无设备数据）")
    else:
        total = len(health)
        lvl = Counter(h[3] for h in health)
        sco = [h[2] for h in health]
        print(f"设备总数: {total}")
        print("分档分布:")
        for k in ("优", "良", "中", "差"):
            c = lvl.get(k, 0)
            print("  " + _bar(k, c, total))
        print(
            f"健康分: min={min(sco)} max={max(sco)} "
            f"mean={sum(sco)/total:.1f} median={sorted(sco)[total//2]}"
        )
        offline = sum(1 for h in health if h[1] == "offline")
        print(f"在线状态: 离线={offline} 非离线={total-offline}")

    print("\n==================== 项目风险分（实时） ====================")
    if not risk:
        print("（无项目数据）")
    else:
        total = len(risk)
        lvl = Counter(r[4] for r in risk)
        idxs = [r[3] for r in risk]
        print(f"项目总数: {total}")
        print("风险分档:")
        for k in ("高", "中", "低"):
            c = lvl.get(k, 0)
            print("  " + _bar(k, c, total))
        print(
            f"风险指数: min={min(idxs)} max={max(idxs)} "
            f"mean={sum(idxs)/total:.1f} median={sorted(idxs)[total//2]}"
        )
        print("逐项目:")
        for pid, name, raw, idx, level in sorted(risk, key=lambda x: -x[3]):
            print(f"  [{level}] {name:<24} risk_index={idx:>3} raw={raw}")


# ---------------------------------------------------------------------------
# 场景矩阵（无需真实数据）
# ---------------------------------------------------------------------------
def print_matrix():
    print("\n==================== 场景 → 分档 矩阵 ====================")
    print("\n-- 设备健康分：在线状态 × 严重告警数（其余告警0，窗口有上报）--")
    print(f"{'在线状态':<10}{'严重':<6}{'警告':<6}{'提示':<6}{'健康分':<8}{'分档'}")
    for state in ("fresh", "stale", "offline"):
        for sev in (0, 1, 3):
            for war in (0, 2):
                for hint in (0, 4):
                    sev_dict = {}
                    if sev:
                        sev_dict["严重"] = sev
                    if war:
                        sev_dict["警告"] = war
                    if hint:
                        sev_dict["提示"] = hint
                    s = device_health_score(
                        online_state=state, reported=True, alarm_severity_counts=sev_dict
                    )
                    print(f"{state:<10}{sev:<6}{war:<6}{hint:<6}{s:<8}{device_health_level(s)}")

    print("\n-- 项目风险分：未处理严重告警数 × 超期重大隐患数（其余0）--")
    print(f"{'未处理严重':<10}{'超期重大':<10}{'风险指数':<10}{'风险分档'}")
    for sev in (0, 1, 2, 4):
        for od in (0, 1, 3):
            raw, idx, level = project_risk_score(
                unhandled_by_level={"严重": sev},
                overdue_by_level={"重大": od} if od else {},
                open_hazards=0,
            )
            print(f"{sev:<10}{od:<10}{idx:<10}{level}")


# ---------------------------------------------------------------------------
# 参数扫描（敏感性）
# ---------------------------------------------------------------------------
def print_sweep():
    print("\n==================== 关键参数敏感性扫描 ====================")
    # 固定一组代表性项目场景（未处理告警按级别）
    scenarios = [
        ("轻", {"提示": 2}),
        ("中", {"警告": 2, "提示": 3}),
        ("重", {"严重": 1, "警告": 2}),
        ("极重", {"严重": 3, "警告": 5, "提示": 6}),
    ]

    print("\n[1] 扫描 RISK_NORMALIZE_K（越大→风险指数越难冲高）")
    for k in (5, 10, 20, 30, 50):
        import app.core.scoring as sc

        sc.RISK_NORMALIZE_K = k
        line = f"  K={k:<3}: "
        for name, ubl in scenarios:
            idx = project_risk_score(unhandled_by_level=ubl)[1]
            line += f"{name}={idx:>3} "
        print(line)

    print("\n[2] 扫描 严重告警权重（ALARM_SEVERITY_WEIGHT['严重']）")
    for w in (2.0, 3.0, 4.0, 5.0):
        import app.core.scoring as sc

        sc.ALARM_SEVERITY_WEIGHT = {"严重": w, "警告": 2.0, "提示": 1.0}
        line = f"  严重权重={w:<4}: "
        for name, ubl in scenarios:
            idx = project_risk_score(unhandled_by_level=ubl)[1]
            line += f"{name}={idx:>3} "
        print(line)

    # 复位（避免影响后续）
    import app.core.scoring as sc

    sc.RISK_NORMALIZE_K = 20.0
    sc.ALARM_SEVERITY_WEIGHT = {"严重": 3.0, "警告": 2.0, "提示": 1.0}
    print("\n（已复位默认权重）")


def main():
    ap = argparse.ArgumentParser(description="评分权重标定回测工具")
    ap.add_argument("--hours", type=int, default=24, help="设备健康统计窗口(小时)")
    ap.add_argument("--days", type=int, default=7, help="项目风险统计窗口(天)")
    ap.add_argument("--weights", type=str, default=None, help="权重覆盖 JSON 路径")
    ap.add_argument("--matrix", action="store_true", help="打印场景→分档矩阵")
    ap.add_argument("--sweep", action="store_true", help="关键参数敏感性扫描")
    args = ap.parse_args()

    if args.weights:
        with open(args.weights, "r", encoding="utf-8") as f:
            apply_weights(json.load(f))
        print(f"[权重覆盖] 已应用: {args.weights}")

    if args.matrix:
        print_matrix()
    if args.sweep:
        print_sweep()

    # 实时回测（除非只想要矩阵/扫描）
    if not (args.matrix or args.sweep) or args.weights:
        db = SessionLocal()
        try:
            health = live_health(db, args.hours)
            risk = live_risk(db, args.days)
        finally:
            db.close()
        print_live(health, risk)

    print("\n完成。")


if __name__ == "__main__":
    main()

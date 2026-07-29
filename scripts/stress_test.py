#!/usr/bin/env python
"""压测常态化编排器（阶段⑥收尾 · 把一次性压测变成可重复、可告警的例行任务）。

解决的问题：
- 阶段⑥已有 `scripts/locustfile.py`（HTTP 查看者负载）+ `scripts/mqtt_flood.py`（千台设备上行洪泛）
  + `scripts/seed_stress.py`（种子设备），但三者是手敲的多条命令，结果散落 stdout / 临时 CSV，
  **无法与历史基线对比、无法趋势化、无法在回归时自动告警**。
- 本脚本把上述三步串成一次「压测运行」，并：
  1. 解析 locust `--csv` 与 mqtt_flood JSON，得到结构化指标；
  2. 与 `baseline.json` 阈值比对，判定 warn / alert（回归）；
  3. 写 `latest.json`（供看板/人读）+ 追加 `history.csv`（供趋势）；
  4. 可选推送 Prometheus Pushgateway（`rail_monitor_stress_*` gauge），Grafana 看板趋势 + 超阈告警；
  5. 退出码：0=健康，1=warn，2=alert（供 systemd/CI 判定失败）。

用法（rail_monitor 目录下，需处于已装依赖的 venv）：
    # 完整跑（默认 1000 设备 @2s + 100 查看者，与 STRESS_TEST_REPORT 同口径）
    .venv/bin/python scripts/stress_test.py

    # 轻量冒烟（CI / 本机快速验证脚本逻辑，不压真实后端）
    .venv/bin/python scripts/stress_test.py --self-test

    # 周期性/受限环境（少设备、短时长、跳过 MQTT 上行）
    .venv/bin/python scripts/stress_test.py --devices 50 --interval 3 --duration 30 \\
        --viewers 10 --no-mqtt --out /var/lib/rail_monitor/stress

    # 推送监控栈（需 deploy/monitoring 已起 pushgateway）
    .venv/bin/python scripts/stress_test.py --pushgateway http://127.0.0.1:9091

配合：
- deploy/scripts/rail-monitor-stress.{service,timer}  —— 定时（默认每周日 03:00 CST）例行跑。
- .github/workflows/stress-test.yml                  —— 周级 scheduled 跑 --self-test 守护脚本健康。
- deploy/grafana-stress-dashboard.json              —— 趋势 + 超阈告警看板。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

DEFAULT_BASELINE = os.path.join(_ROOT, "deploy", "stress-test", "baseline.json")

# ---------------------------------------------------------------------------
# 指标解析（对 locust stats CSV 的列名做容错匹配，兼容 2.x 输出差异）
# ---------------------------------------------------------------------------


def _cell(row: dict, *aliases: str):
    """按精确名或子串匹配取列值； locust 不同版本列名略有差异。"""
    for a in aliases:
        if a in row:
            return row[a]
    low = [a.lower() for a in aliases]
    for k, v in row.items():
        kl = k.lower()
        if any(a in kl for a in low):
            return v
    return None


def _to_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_locust_stats(csv_path: str) -> dict:
    """解析 locust `--csv` 产出的 `_stats.csv`，返回真实端点聚合 + 各端点明细。

    真实端点 = 排除 media/access（该端点预期 404，不计入 SLO）。
    """
    per_endpoint: list[dict] = []
    real_req = real_fail = 0.0
    real_rps = 0.0
    real_p95_max = 0.0
    media_fail = 0.0
    media_req = 0.0
    if not os.path.exists(csv_path):
        return {
            "per_endpoint": per_endpoint,
            "http_requests": 0,
            "http_fails": 0,
            "http_error_rate": 0.0,
            "http_rps": 0.0,
            "http_p95_ms": 0.0,
            "media_requests": 0,
            "media_fails": 0,
        }
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("Name") or "").strip()
            if name == "Aggregated" or not name:
                continue
            # 兼容 locust 不同版本列名：2.45 为 "Request Count"/"Failure Count"/
            # "Requests/s"/"95%"，旧版为 "Requests"/"Fails"/"Total RPS"/"95%ile (ms)"
            req = _to_float(_cell(row, "Request Count", "Requests"))
            fail = _to_float(_cell(row, "Failure Count", "Fails"))
            rps = _to_float(_cell(row, "Requests/s", "Total RPS", "Current RPS"))
            p95 = _to_float(_cell(row, "95%", "95%ile (ms)", "95%ile"))
            per_endpoint.append(
                {"name": name, "requests": req, "fails": fail, "rps": rps, "p95_ms": p95}
            )
            if "media" in name.lower():
                media_req += req
                media_fail += fail
            else:
                real_req += req
                real_fail += fail
                real_rps += rps
                real_p95_max = max(real_p95_max, p95)
    return {
        "per_endpoint": per_endpoint,
        "http_requests": int(real_req),
        "http_fails": int(real_fail),
        "http_error_rate": (real_fail / real_req) if real_req else 0.0,
        "http_rps": round(real_rps, 2),
        "http_p95_ms": round(real_p95_max, 1),
        "media_requests": int(media_req),
        "media_fails": int(media_fail),
    }


def parse_mqtt_summary(json_path: str) -> dict:
    """解析 mqtt_flood 输出的吞吐摘要 JSON。"""
    if not os.path.exists(json_path):
        return {"published": 0, "errors": 0, "rate_msg_per_s": 0.0, "duration_s": 0.0}
    with open(json_path, encoding="utf-8") as f:
        s = json.load(f)
    published = int(s.get("published", 0))
    errors = int(s.get("errors", 0))
    rate = _to_float(s.get("rate_msg_per_s"))
    return {
        "published": published,
        "errors": errors,
        "rate_msg_per_s": rate,
        "error_rate": (errors / published) if published else 0.0,
        "duration_s": _to_float(s.get("duration_s")),
    }


# ---------------------------------------------------------------------------
# 基线比对
# ---------------------------------------------------------------------------


def load_baseline(path: str) -> dict:
    if not os.path.exists(path):
        return {"thresholds": {}}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _level_for(metric: str, value: float, thr: dict) -> str:
    """根据阈值方向判定 ok / warn / alert。

    阈值约定：值越低越差  → 用 warn_lt / alert_lt；值越高越差 → 用 warn_gt / alert_gt。
    """
    if not thr:
        return "ok"
    if "alert_lt" in thr and value < thr["alert_lt"]:
        return "alert"
    if "warn_lt" in thr and value < thr["warn_lt"]:
        return "warn"
    if "alert_gt" in thr and value > thr["alert_gt"]:
        return "alert"
    if "warn_gt" in thr and value > thr["warn_gt"]:
        return "warn"
    return "ok"


def compare_to_baseline(combined: dict, baseline: dict) -> dict:
    thr = baseline.get("thresholds", {})
    checks = []
    worst = "ok"
    order = {"ok": 0, "warn": 1, "alert": 2}
    for metric in ("http_rps", "http_p95_ms", "http_error_rate", "mqtt_rate", "mqtt_error_rate"):
        if metric == "mqtt_rate":
            val = combined.get("mqtt_rate", 0.0)
        elif metric == "mqtt_error_rate":
            val = combined.get("mqtt_error_rate", 0.0)
        else:
            val = combined.get(metric, 0.0)
        lvl = _level_for(metric, val, thr.get(metric, {}))
        checks.append({"metric": metric, "value": round(val, 4), "level": lvl})
        if order[lvl] > order[worst]:
            worst = lvl
    return {"status": worst, "checks": checks}


# ---------------------------------------------------------------------------
# Prometheus Pushgateway（可选）
# ---------------------------------------------------------------------------


def push_to_pgateway(combined: dict, comparison: dict, pushgateway: str, env: str) -> bool:
    try:
        from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
    except Exception as e:  # pragma: no cover
        print(f"[stress] 跳过 Pushgateway（prometheus_client 不可用: {e}）")
        return False
    reg = CollectorRegistry()
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    common = dict(run_ts=run_ts, env=env)
    gauges = {
        "rail_monitor_stress_http_rps": combined.get("http_rps", 0.0),
        "rail_monitor_stress_http_p95_ms": combined.get("http_p95_ms", 0.0),
        "rail_monitor_stress_http_error_rate": combined.get("http_error_rate", 0.0),
        "rail_monitor_stress_mqtt_rate": combined.get("mqtt_rate", 0.0),
        "rail_monitor_stress_mqtt_error_rate": combined.get("mqtt_error_rate", 0.0),
        "rail_monitor_stress_status": {"ok": 0, "warn": 1, "alert": 2}.get(
            comparison.get("status", "ok"), 0
        ),
    }
    for name, val in gauges.items():
        g = Gauge(name, name, labelnames=["run_ts", "env"], registry=reg)
        g.labels(**common).set(val)
    try:
        push_to_gateway(pushgateway, job="rail_monitor_stress", registry=reg)
        print(f"[stress] 已推送指标到 Pushgateway {pushgateway}")
        return True
    except Exception as e:  # pragma: no cover
        print(f"[stress] 推送 Pushgateway 失败: {e}")
        return False


# ---------------------------------------------------------------------------
# 进程编排
# ---------------------------------------------------------------------------


def _run(cmd, cwd, env, **kw):
    print(f"[stress] $ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd, env=env, **kw)


def run_seed_stress(python_bin: str, cwd: str, env: dict) -> None:
    _run([python_bin, "scripts/seed_stress.py"], cwd=cwd, env=env, check=True)


def run_mqtt_flood(python_bin: str, cwd: str, env: dict, args: argparse.Namespace, out_json: str):
    cmd = [
        python_bin,
        "scripts/mqtt_flood.py",
        "--devices",
        str(args.devices),
        "--interval",
        str(args.interval),
        "--duration",
        str(args.duration + 5),  # 略长于 HTTP，保证重叠
        "--broker",
        args.mqtt_broker,
        "--port",
        str(args.mqtt_port),
        "--out",
        out_json,
    ]
    return subprocess.Popen(cmd, cwd=cwd, env=env)


def run_locust(
    python_bin: str, cwd: str, env: dict, args: argparse.Namespace, csv_prefix: str
) -> int:
    cmd = [
        python_bin,
        "-m",
        "locust",
        "-f",
        "scripts/locustfile.py",
        "ViewerUser",
        "--headless",
        "-u",
        str(args.viewers),
        "-r",
        str(args.spawn_rate),
        "-t",
        f"{args.duration}s",
        "--csv",
        csv_prefix,
        "--host",
        args.host,
    ]
    return _run(cmd, cwd=cwd, env=env, check=True).returncode


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def build_combined(locust_stats: dict, mqtt_summary: dict) -> dict:
    return {
        "http_requests": locust_stats["http_requests"],
        "http_fails": locust_stats["http_fails"],
        "http_error_rate": round(locust_stats["http_error_rate"], 4),
        "http_rps": locust_stats["http_rps"],
        "http_p95_ms": locust_stats["http_p95_ms"],
        "media_requests": locust_stats["media_requests"],
        "media_fails": locust_stats["media_fails"],
        "mqtt_published": mqtt_summary["published"],
        "mqtt_errors": mqtt_summary["errors"],
        "mqtt_rate": round(mqtt_summary["rate_msg_per_s"], 1),
        "mqtt_error_rate": round(mqtt_summary.get("error_rate", 0.0), 4),
    }


def write_outputs(out_dir: str, combined: dict, comparison: dict, args: argparse.Namespace) -> None:
    os.makedirs(out_dir, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    latest = {
        "run_id": run_id,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "host": args.host,
            "viewers": args.viewers,
            "devices": args.devices,
            "interval": args.interval,
            "duration_s": args.duration,
        },
        "metrics": combined,
        "comparison": comparison,
    }
    with open(os.path.join(out_dir, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)

    history_path = os.path.join(out_dir, "history.csv")
    header = [
        "run_id",
        "run_at",
        "http_rps",
        "http_p95_ms",
        "http_error_rate",
        "http_requests",
        "mqtt_rate",
        "mqtt_error_rate",
        "mqtt_published",
        "status",
    ]
    row = [
        run_id,
        latest["run_at"],
        combined["http_rps"],
        combined["http_p95_ms"],
        combined["http_error_rate"],
        combined["http_requests"],
        combined["mqtt_rate"],
        combined["mqtt_error_rate"],
        combined["mqtt_published"],
        comparison["status"],
    ]
    write_header = not os.path.exists(history_path)
    with open(history_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(header)
        w.writerow(row)


def _print_summary(combined: dict, comparison: dict) -> None:
    print("\n================ 压测结果 ================")
    print(f"  HTTP 真实端点 RPS : {combined['http_rps']}")
    print(f"  HTTP P95 (ms)     : {combined['http_p95_ms']}")
    print(f"  HTTP 错误率       : {combined['http_error_rate']*100:.2f}%")
    print(f"  MQTT 上行速率      : {combined['mqtt_rate']} msg/s")
    print(f"  MQTT 错误率       : {combined['mqtt_error_rate']*100:.2f}%")
    print("  ---- 基线比对 ----")
    for c in comparison["checks"]:
        mark = {"ok": "✅", "warn": "⚠️ ", "alert": "❌"}.get(c["level"], "?")
        print(f"   {mark} {c['metric']:18s} = {c['value']}")
    print(f"  总判定: {comparison['status'].upper()}")
    print("==========================================\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Rail Monitor 压测常态化编排器")
    ap.add_argument("--host", default=os.getenv("STRESS_HOST", "http://127.0.0.1:8000"))
    ap.add_argument("--viewers", type=int, default=int(os.getenv("STRESS_VIEWERS", "100")))
    ap.add_argument("--spawn-rate", type=float, default=float(os.getenv("STRESS_SPAWN_RATE", "20")))
    ap.add_argument("--devices", type=int, default=int(os.getenv("STRESS_DEVICES", "1000")))
    ap.add_argument("--interval", type=float, default=float(os.getenv("STRESS_INTERVAL", "2")))
    ap.add_argument("--duration", type=int, default=int(os.getenv("STRESS_DURATION", "180")))
    ap.add_argument("--mqtt-broker", default=os.getenv("MQTT_BROKER", "127.0.0.1"))
    ap.add_argument("--mqtt-port", type=int, default=int(os.getenv("MQTT_PORT", "1883")))
    ap.add_argument("--out", default=os.getenv("STRESS_OUT", "/tmp/rail_stress"))
    ap.add_argument("--baseline", default=DEFAULT_BASELINE)
    ap.add_argument("--pushgateway", default=os.getenv("STRESS_PUSHGATEWAY", ""))
    ap.add_argument("--env-tag", default=os.getenv("STRESS_ENV", "prod"))
    ap.add_argument("--no-mqtt", action="store_true", help="跳过 MQTT 上行（仅 HTTP 查看者负载）")
    ap.add_argument("--no-http", action="store_true", help="跳过 HTTP 负载（仅 MQTT 上行）")
    ap.add_argument("--no-seed", action="store_true", help="跳过 seed_stress（设备已存在时）")
    ap.add_argument(
        "--self-test",
        action="store_true",
        help="使用内嵌样例数据校验解析/比对逻辑，不启动任何压测进程",
    )
    args = ap.parse_args()

    if args.self_test:
        return _self_test()

    cwd = _ROOT
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", cwd)
    python_bin = sys.executable

    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)
    locust_csv = os.path.join(out_dir, "locust")
    mqtt_json = os.path.join(out_dir, "mqtt_flood.json")

    if not args.no_seed and not args.no_mqtt:
        print("[stress] 1/4 种子压测设备 ...")
        run_seed_stress(python_bin, cwd, env)

    mqtt_proc = None
    if not args.no_mqtt:
        print("[stress] 2/4 启动 MQTT 上行洪泛（后台）...")
        mqtt_proc = run_mqtt_flood(python_bin, cwd, env, args, mqtt_json)

    if not args.no_http:
        print("[stress] 3/4 运行 Locust HTTP 查看者负载 ...")
        run_locust(python_bin, cwd, env, args, locust_csv)

    if mqtt_proc is not None:
        print("[stress] 等待 MQTT 洪泛结束 ...")
        mqtt_proc.wait()

    print("[stress] 4/4 解析结果 + 基线比对 ...")
    locust_stats = parse_locust_stats(f"{locust_csv}_stats.csv")
    mqtt_summary = parse_mqtt_summary(mqtt_json)
    combined = build_combined(locust_stats, mqtt_summary)
    baseline = load_baseline(args.baseline)
    comparison = compare_to_baseline(combined, baseline)
    write_outputs(out_dir, combined, comparison, args)
    _print_summary(combined, comparison)

    if args.pushgateway:
        push_to_pgateway(combined, comparison, args.pushgateway, args.env_tag)

    return {"ok": 0, "warn": 1, "alert": 2}[comparison["status"]]


# ---------------------------------------------------------------------------
# 自测（不依赖运行中的后端）
# ---------------------------------------------------------------------------


def _self_test() -> int:
    sample_stats_csv = """Type,Name,Request Count,Failure Count,Median Response Time,Average Response Time,Min Response Time,Max Response Time,Average Content Size,Requests/s,Failures/s,50%,66%,75%,80%,90%,95%,98%,99%,99.9%,99.99%,100%
GET,dashboard/stats,1453,0,24,40,8,2100,120,12.13,0,24,180,200,240,280,320,360,1100,1100,1100,1100
GET,alarms/list,1465,0,38,55,10,1900,120,12.23,0,38,150,200,250,300,370,372,372,372,372,372
GET,realtime/locations,1132,0,31,42,9,1500,80,9.45,0,31,130,180,200,250,290,300,400,400,400,400
GET,realtime/online-status,592,0,31,40,8,1200,60,4.94,0,31,130,160,180,200,250,260,330,330,330,330
GET,devices/list,838,0,53,70,12,2000,100,6.99,0,53,180,220,250,300,470,480,520,520,520,520
GET,media/access,269,269,27,35,15,900,0,2.24,2.24,27,110,150,180,200,390,400,500,500,500,500
"""
    sample_mqtt = {
        "published": 76000,
        "errors": 0,
        "rate_msg_per_s": 495.4,
        "duration_s": 153.0,
    }
    tmp = Path("/tmp/_stress_selftest")
    tmp.mkdir(exist_ok=True)
    csv_path = tmp / "locust_stats.csv"
    csv_path.write_text(sample_stats_csv, encoding="utf-8")
    mqtt_path = tmp / "mqtt_flood.json"
    mqtt_path.write_text(json.dumps(sample_mqtt), encoding="utf-8")

    stats = parse_locust_stats(str(csv_path))
    mqtt = parse_mqtt_summary(str(mqtt_path))
    combined = build_combined(stats, mqtt)
    baseline = {
        "thresholds": {
            "http_rps": {"warn_lt": 40, "alert_lt": 30},
            # 真实端点中最慢 P95（devices/list）基线约 470ms，留余量
            "http_p95_ms": {"warn_gt": 600, "alert_gt": 1000},
            "http_error_rate": {"warn_gt": 0.01, "alert_gt": 0.05},
            "mqtt_rate": {"warn_lt": 450, "alert_lt": 350},
            "mqtt_error_rate": {"warn_gt": 0.01, "alert_gt": 0.05},
        }
    }
    comp = compare_to_baseline(combined, baseline)

    ok = True
    # 真实端点应排除 media（269 失败不应计入错误率）
    assert stats["http_requests"] == 1453 + 1465 + 1132 + 592 + 838, stats["http_requests"]
    assert stats["http_fails"] == 0, stats["http_fails"]
    assert abs(stats["http_error_rate"] - 0.0) < 1e-9, stats["http_error_rate"]
    assert abs(stats["http_rps"] - (12.13 + 12.23 + 9.45 + 4.94 + 6.99)) < 0.01, stats["http_rps"]
    assert stats["http_p95_ms"] == 470, stats["http_p95_ms"]  # devices/list 的 470 为最大
    assert combined["mqtt_rate"] == 495.4, combined["mqtt_rate"]
    assert comp["status"] == "ok", comp  # 全部在基线内

    # 构造一个回归场景：HTTP RPS 骤降 + P95 飙升
    bad_combined = dict(combined)
    bad_combined["http_rps"] = 25.0
    bad_combined["http_p95_ms"] = 900.0
    bad_comp = compare_to_baseline(bad_combined, baseline)
    assert bad_comp["status"] == "alert", bad_comp
    # 构造一个 warn 场景
    warn_combined = dict(combined)
    warn_combined["http_rps"] = 35.0
    warn_comp = compare_to_baseline(warn_combined, baseline)
    assert warn_comp["status"] == "warn", warn_comp

    print("self-test PASS:")
    print(f"  http_rps={combined['http_rps']} (real endpoints, media excluded)")
    print(f"  http_p95_ms={combined['http_p95_ms']}  http_error_rate={combined['http_error_rate']}")
    print(f"  mqtt_rate={combined['mqtt_rate']}")
    print(f"  baseline status (sample) = {comp['status']}")
    print(f"  regression status (rps=25,p95=900) = {bad_comp['status']}")
    print(f"  warn status (rps=35) = {warn_comp['status']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

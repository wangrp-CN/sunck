"""离线几何校验：seed_demo 围栏 与 device_simulator 巡逻路径 的相交/间距关系。

目的：在真正启动 broker/PG 联调之前，先证明「几何前提」成立——
定位设备巡逻时会落入围栏（触发 fence_intrusion）且会靠近大机（触发 distance_too_close）。

不依赖 PG/MQTT，仅需 shapely + app.core.geo。
复用 seed_demo / device_simulator 的常量，避免坐标硬编码漂移。

用法（rail_monitor 目录下）：
    .venv/bin/python scripts/verify_simulator_geo.py
"""

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from shapely import Point, wkt  # noqa: E402

from app.core.geo import haversine_meters  # noqa: E402

import seed_demo as sd  # _FENCE_WKT, _FENCE_CENTER  # noqa: E402
import device_simulator as sim  # LOCATE_PATH, AI_LNG, AI_LAT  # noqa: E402

# 与 AlarmConfig.distance_machine 默认阈值一致（seed_demo 也设为 50）
DISTANCE_THRESHOLD = 50


def main() -> int:
    fence = wkt.loads(sd._FENCE_WKT)
    center = sd._FENCE_CENTER
    print(f"围栏中心(WGS-84): {center}")
    print(f"间距阈值: {DISTANCE_THRESHOLD}m（大机 {sim.AI_NO} @ {sim.AI_LNG},{sim.AI_LAT}）")
    print("=" * 64)
    print("巡逻路径点 → 围栏侵入 / 大机间距判定：")
    print("-" * 64)

    fence_hits = 0
    near_hits = 0
    for i, (lng, lat) in enumerate(sim.LOCATE_PATH):
        inside = fence.contains(Point(lng, lat))
        d_ai = haversine_meters(lng, lat, sim.AI_LNG, sim.AI_LAT)
        near = d_ai < DISTANCE_THRESHOLD
        fence_hits += int(inside)
        near_hits += int(near)
        tag = []
        if inside:
            tag.append("围栏侵入")
        if near:
            tag.append("间距告警")
        print(
            f"  点{i:>2} ({lng:.4f},{lat:.4f}): 围栏内={str(inside):<5} "
            f"距大机={d_ai:6.1f}m  触发={','.join(tag) or '无'}"
        )

    print("-" * 64)
    print(f"落入围栏的点: {fence_hits}/{len(sim.LOCATE_PATH)}")
    print(f"靠近大机的点: {near_hits}/{len(sim.LOCATE_PATH)}")

    ok = True
    if fence_hits < 3:
        print("❌ 落入围栏的点不足 3 个，无法稳定触发围栏侵入告警")
        ok = False
    if near_hits < 1:
        print("❌ 无路径点靠近大机，无法触发间距告警")
        ok = False
    # 验证围栏坐标与模拟器所用中心一致
    if abs(center[0] - sim.AI_LNG) > 1e-3 or abs(center[1] - sim.AI_LAT) > 1e-3:
        print("❌ 大机坐标偏离围栏中心，seed 与模拟器可能对不齐")
        ok = False

    print("=" * 64)
    print("几何校验：" + ("全部通过 ✅" if ok else "存在失败 ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

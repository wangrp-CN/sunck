"""实时链路端到端联调的 pytest 包装（阶段1 → 联调里程碑）。

默认 `pytest` 会跳过本用例（避免每次跑重进程的 MQTT/PG/Redis 联调）。
需要时显式开启：

    RUN_E2E=1 pytest -m integration          # 仅跑联调
    RUN_E2E=1 pytest                          # 全量（含联调）

核心逻辑在 scripts/realtime_integration.py 的 run_e2e()，本文件只做：
- 导入并断言 run_e2e() 全绿；
- 失败时把每一步的 OK/FAIL 明细打到 pytest 报告中，便于定位断裂点。
"""

import os

import pytest

# pythonpath=['.'] 已将仓库根加入 sys.path，scripts 以命名空间包导入。
from scripts.realtime_integration import run_e2e  # noqa: E402

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not os.getenv("RUN_E2E"),
    reason="实时链路端到端联调需本地原生服务，置 RUN_E2E=1 启用",
)
def test_realtime_end_to_end():
    """真实 MQTT broker + 真实 FastAPI 进程，跑通上行/下行全链路。"""
    ok, steps = run_e2e(verbose=False)
    detail = "\n".join(
        f"  {'✅' if s['ok'] else '❌'} {s['step']}" + (f" — {s['detail']}" if s["detail"] else "")
        for s in steps
    )
    assert ok, f"实时链路联调未全部通过：\n{detail}"

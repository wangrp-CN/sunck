"""处置预案播种脚本。

用法（在 rail_monitor 目录下）：
    .venv/bin/python scripts/seed_playbooks.py

会创建 6 类告警的默认处置预案（mock），幂等可重复执行。
"""

import os
import sys

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.core.playbook_seed import seed_playbooks  # noqa: E402


def main() -> None:
    stats = seed_playbooks()
    print("处置预案播种完成：")
    print(f"  新增：{stats['created']}")
    print(f"  已存在跳过：{stats['skipped']}")


if __name__ == "__main__":
    main()

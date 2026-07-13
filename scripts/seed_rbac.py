"""RBAC 数据播种脚本。

用法（在 rail_monitor 目录下）：
    .venv/bin/python scripts/seed_rbac.py

会创建默认权限、角色与超级管理员账号（admin / Admin@123456）。
"""

import os
import sys

# 将项目根目录加入路径，确保 `import app` 可用
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.config import settings  # noqa: E402
from app.core.rbac_seed import seed_rbac  # noqa: E402


def main() -> None:
    stats = seed_rbac()
    print("RBAC 播种完成：")
    print(f"  新增权限：{stats['permissions']}")
    print(f"  新增角色：{stats['roles']}")
    print(f"  新增部门：{stats['departments']}")
    print(f"  新增用户：{stats['users']}")
    print(
        f"  超级管理员账号：{settings.default_admin_username} / {settings.default_admin_password}"
    )


if __name__ == "__main__":
    main()

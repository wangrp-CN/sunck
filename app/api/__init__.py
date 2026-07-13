"""API 路由层。

v1 路由在 api/router.py 中汇总，main.py 通过 `include_router` 挂载到 `/api`。
骨架阶段每个模块仅提供 `/ping` 占位，后续按《开发计划》阶段实现业务逻辑。
"""

from app.api.router import api_router  # noqa: F401

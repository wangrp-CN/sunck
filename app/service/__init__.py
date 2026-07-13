"""业务逻辑层（service）。

骨架阶段仅提供通用 CRUD 基类 `CRUDService`，各域服务后续在此包下按模块实现。
业务层依赖 model（ORM）与 core（db/redis/security），不直接依赖 api 层。
"""

from app.service.base import CRUDService  # noqa: F401

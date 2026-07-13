"""数据校验/序列化层（Pydantic v2）。

放置跨域公共结构（分页、统一响应）与各模块的请求/响应模型。
骨架阶段仅提供公共结构与认证示例，业务模型后续按模块补充。
"""

from app.schema.common import ApiResponse, Page, PageQuery  # noqa: F401

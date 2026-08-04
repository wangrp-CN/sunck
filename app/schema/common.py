"""公共 Schema：统一响应、分页查询与分页结果。"""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from app.core.responses import ApiResponse

T = TypeVar("T")


class PageQuery(BaseModel):
    """列表分页通用查询参数。"""

    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=200, description="每页条数")


class Page(BaseModel, Generic[T]):
    """分页结果包装。"""

    items: list[T] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class IdList(BaseModel):
    """批量操作请求体：待操作记录的主键列表。"""

    ids: list[int] = Field(..., description="待操作记录的主键列表（1~200 个）", max_length=200)


__all__ = ["ApiResponse", "PageQuery", "Page", "IdList", "T"]

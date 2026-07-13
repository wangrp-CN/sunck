"""统一 API 响应结构（泛型）。

约定：所有业务接口返回 `ApiResponse[T]`；`code=0` 表示成功，非 0 表示业务失败。
异常由 core.exceptions 统一转换为相同结构（含 HTTP 异常）。
"""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "ok"
    data: T | None = None

    @classmethod
    def success(cls, data: Any | None = None, message: str = "ok") -> "ApiResponse":
        return cls(code=0, message=message, data=data)

    @classmethod
    def fail(cls, message: str, code: int = 1, data: Any | None = None) -> "ApiResponse":
        return cls(code=code, message=message, data=data)

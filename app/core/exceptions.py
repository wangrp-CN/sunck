"""自定义异常与全局异常处理器。

将业务异常、参数校验错误与 HTTP 异常统一转换为 `ApiResponse` 结构，
确保前端以一致的字段（code/message/data）处理所有响应。
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.responses import ApiResponse

# HTTP 状态码 -> 中文默认提示
_STATUS_MESSAGES = {
    400: "请求参数错误",
    401: "未认证，请先登录",
    403: "无权限执行该操作",
    404: "资源不存在",
    405: "请求方法不被允许",
    409: "资源冲突",
    422: "参数校验失败",
    423: "账户已被锁定",
    429: "请求过于频繁",
    500: "服务器内部错误",
}


class BusinessError(Exception):
    """通用业务异常。"""

    def __init__(self, message: str = "业务处理失败", code: int = 1):
        self.message = message
        self.code = code
        super().__init__(message)


class NotFoundError(BusinessError):
    def __init__(self, message: str = "资源不存在"):
        super().__init__(message=message, code=404)


class ForbiddenError(BusinessError):
    def __init__(self, message: str = "无权限执行该操作"):
        super().__init__(message=message, code=403)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BusinessError)
    async def _biz(_: Request, exc: BusinessError):
        return JSONResponse(
            status_code=200, content=ApiResponse.fail(exc.message, exc.code).model_dump()
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=200,
            content=ApiResponse.fail("参数校验失败", code=422, data=exc.errors()).model_dump(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        # 统一为 ApiResponse 结构；HTTP 状态码保留以示意错误类别
        message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        code = exc.status_code
        return JSONResponse(
            status_code=code,
            content=ApiResponse.fail(
                message or _STATUS_MESSAGES.get(code, "请求处理失败"), code=code
            ).model_dump(),
        )

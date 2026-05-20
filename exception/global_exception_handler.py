from fastapi import Request, status
from fastapi.responses import JSONResponse
from exception.bad_request_exception import BadRequestException


async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器"""
    if isinstance(exc, BadRequestException):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"status": 0, "message": exc.message, "data": None}
        )
    
    # 处理其他异常
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"status": 0, "message": "服务器内部错误", "data": None}
    )

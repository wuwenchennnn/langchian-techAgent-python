from pydantic import BaseModel
from typing import Optional


class ChatResponse(BaseModel):
    """聊天响应模型"""
    status: int
    message: str
    data: Optional[str] = None


class UploadResponse(BaseModel):
    """上传文件响应模型"""
    success: bool
    message: str
    textLength: int


class SessionResponse(BaseModel):
    """会话管理响应模型"""
    success: bool
    message: str

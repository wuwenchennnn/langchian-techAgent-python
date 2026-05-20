from pydantic import BaseModel


class ChatRequest(BaseModel):
    """聊天请求模型"""
    memoryId: str
    message: str


class SessionRequest(BaseModel):
    """会话管理请求模型"""
    memoryId: str

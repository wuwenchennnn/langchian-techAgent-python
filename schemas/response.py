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
    grade: str
    className: str
    examName: str
    bucketId: str


class SessionResponse(BaseModel):
    """会话管理响应模型"""
    success: bool
    message: str


class DocumentInfo(BaseModel):
    """桶内单份考试文档信息"""
    examName: str
    filename: str
    uploadedAt: str
    textLength: int
    studentCount: int
    subjectCount: int


class BucketInfo(BaseModel):
    """（年级 + 班级）桶信息"""
    grade: str
    className: str
    bucketId: str
    documents: list[DocumentInfo]


class BucketListResponse(BaseModel):
    """已有桶列表响应"""
    success: bool
    buckets: list[BucketInfo]

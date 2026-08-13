from pydantic import BaseModel
from typing import Optional


class ChatResponse(BaseModel):
    """聊天响应模型"""
    status: int
    message: str
    data: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": 1,
                    "message": "成功",
                    "data": "高一3班期末考试语文平均分 87.7 分，优秀率 80%……",
                }
            ]
        }
    }


class UploadResponse(BaseModel):
    """上传文件响应模型"""
    success: bool
    message: str
    textLength: int
    grade: str
    className: str
    examName: str
    bucketId: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "message": "成绩单上传成功（10名学生），可在该班级会话中请求分析",
                    "textLength": 268,
                    "grade": "高一",
                    "className": "3班",
                    "examName": "期中考试",
                    "bucketId": "高一::3班",
                }
            ]
        }
    }


class SessionResponse(BaseModel):
    """会话管理响应模型"""
    success: bool
    message: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"success": True, "message": "会话数据已清除"}
            ]
        }
    }


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

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "buckets": [
                        {
                            "grade": "高一",
                            "className": "3班",
                            "bucketId": "高一::3班",
                            "documents": [
                                {
                                    "examName": "期中考试",
                                    "filename": "高一3班期中.xlsx",
                                    "uploadedAt": "2026-08-10 15:30:19",
                                    "textLength": 268,
                                    "studentCount": 10,
                                    "subjectCount": 3,
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    }

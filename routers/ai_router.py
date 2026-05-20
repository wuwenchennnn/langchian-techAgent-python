from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from ai_service.consultant_service import ConsultantService
from service.grade_document_service import GradeDocumentService
from repository.redis_chat_memory_store import RedisChatMemoryStore
from schemas.response import ChatResponse, UploadResponse, SessionResponse
from exception.bad_request_exception import BadRequestException

router = APIRouter(prefix="/ai", tags=["ai"])

# 初始化服务
consultant_service = ConsultantService()
grade_document_service = GradeDocumentService()
redis_chat_memory_store = RedisChatMemoryStore()


@router.post("/upload", response_model=UploadResponse)
async def upload_grade_document(
    memoryId: str = Form(...),
    file: UploadFile = File(...)
) -> UploadResponse:
    """上传成绩文档"""
    try:
        extracted_text = grade_document_service.upload_and_store(memoryId, file)
        length = len(extracted_text) if extracted_text else 0
        return UploadResponse(
            success=True,
            message="成绩单上传成功，可在此会话中请求分析",
            textLength=length
        )
    except ValueError as e:
        raise BadRequestException(str(e))


@router.get("/chat", response_model=ChatResponse)
async def chat(
    memoryId: str,
    message: str
) -> ChatResponse:
    """非流式对话"""
    if not memoryId or memoryId.isspace():
        raise BadRequestException("memoryId 不能为空")
    if not message or message.isspace():
        raise BadRequestException("message 不能为空")

    grade_text = grade_document_service.get_relevant_content(memoryId, message)
    effective_message = message
    if grade_text and grade_text.strip():
        effective_message = f"【检索到的成绩数据（RAG）】\n{grade_text}\n\n【用户问题】\n{message}"

    try:
        full_text = consultant_service.chat(memoryId, effective_message)
        return ChatResponse(status=1, message="成功", data=full_text)
    except Exception as e:
        return ChatResponse(status=0, message=str(e), data=None)


@router.delete("/session", response_model=SessionResponse)
async def close_session(memoryId: str) -> SessionResponse:
    """关闭会话：同时删除该 memoryId 对应的聊天记忆（Redis）和向量数据"""
    if not memoryId or memoryId.isspace():
        raise BadRequestException("memoryId 不能为空")
    # 删除聊天记忆
    redis_chat_memory_store.delete_messages(memoryId)
    # 删除向量库
    grade_document_service.delete(memoryId)
    return SessionResponse(success=True, message="会话数据已清除")


@router.delete("/document", response_model=SessionResponse)
async def delete_document(memoryId: str) -> SessionResponse:
    """删除文档"""
    if not memoryId or memoryId.isspace():
        raise BadRequestException("memoryId 不能为空")
    grade_document_service.delete(memoryId)
    return SessionResponse(success=True, message="成绩文档已清除")

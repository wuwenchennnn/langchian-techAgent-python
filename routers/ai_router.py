from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import StreamingResponse
from ai_service.consultant_service import ConsultantService
from service.grade_document_service import GradeDocumentService
from repository.redis_chat_memory_store import RedisChatMemoryStore
from schemas.response import ChatResponse, UploadResponse, SessionResponse
from exception.bad_request_exception import BadRequestException
import json

router = APIRouter(prefix="/ai", tags=["ai"])

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

        # 检查是否解析到结构化数据
        analyzer = grade_document_service.get_analyzer(memoryId)
        student_count = len(analyzer._student_names) if analyzer else 0

        return UploadResponse(
            success=True,
            message=f"成绩单上传成功（{student_count}名学生），可在此会话中请求分析",
            textLength=length
        )
    except ValueError as e:
        raise BadRequestException(str(e))


@router.get("/chat", response_model=ChatResponse)
async def chat(
    memoryId: str = Query(...),
    message: str = Query(...)
) -> ChatResponse:
    """非流式对话"""
    if not memoryId or memoryId.isspace():
        raise BadRequestException("memoryId 不能为空")
    if not message or message.isspace():
        raise BadRequestException("message 不能为空")

    analyzer = grade_document_service.get_analyzer(memoryId)

    def search_fn(q):
        return grade_document_service.get_relevant_content(memoryId, q)

    try:
        full_text = await consultant_service.chat(memoryId, message, analyzer, search_fn)
        return ChatResponse(status=1, message="成功", data=full_text)
    except Exception as e:
        return ChatResponse(status=0, message=str(e), data=None)


@router.get("/chat/stream")
async def chat_stream(
    memoryId: str = Query(...),
    message: str = Query(...)
):
    """SSE 流式对话"""
    if not memoryId or memoryId.isspace():
        raise BadRequestException("memoryId 不能为空")
    if not message or message.isspace():
        raise BadRequestException("message 不能为空")

    analyzer = grade_document_service.get_analyzer(memoryId)

    def search_fn(q):
        return grade_document_service.get_relevant_content(memoryId, q)

    async def event_generator():
        try:
            async for token in consultant_service.chat_stream(
                memoryId, message, analyzer, search_fn
            ):
                if token:
                    yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.delete("/session", response_model=SessionResponse)
async def close_session(memoryId: str) -> SessionResponse:
    """关闭会话：同时删除聊天记忆、向量数据和结构化分析"""
    if not memoryId or memoryId.isspace():
        raise BadRequestException("memoryId 不能为空")
    redis_chat_memory_store.delete_messages(memoryId)
    grade_document_service.delete(memoryId)
    consultant_service.delete_memory(memoryId)
    return SessionResponse(success=True, message="会话数据已清除")


@router.delete("/document", response_model=SessionResponse)
async def delete_document(memoryId: str) -> SessionResponse:
    """删除文档"""
    if not memoryId or memoryId.isspace():
        raise BadRequestException("memoryId 不能为空")
    grade_document_service.delete(memoryId)
    return SessionResponse(success=True, message="成绩文档已清除")
from fastapi import APIRouter, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from ai_service.consultant_service import ConsultantService
from service.grade_document_service import GradeDocumentService
from repository.redis_chat_memory_store import RedisChatMemoryStore
from repository.redis_grade_document_store import bucket_key
from schemas.response import (
    ChatResponse, UploadResponse, SessionResponse,
    BucketListResponse, BucketInfo, DocumentInfo,
)
from exception.bad_request_exception import BadRequestException
import json

router = APIRouter(prefix="/ai", tags=["ai"])

consultant_service = ConsultantService()
grade_document_service = GradeDocumentService()
redis_chat_memory_store = RedisChatMemoryStore()


def _require_scope(grade: str, className: str, exam_name: str = None):
    """校验年级/班级/考试名称非空，返回去除首尾空格后的值"""
    grade = (grade or "").strip()
    className = (className or "").strip()
    if not grade:
        raise BadRequestException("年级不能为空")
    if not className:
        raise BadRequestException("班级不能为空")
    if exam_name is not None:
        exam_name = (exam_name or "").strip()
        if not exam_name:
            raise BadRequestException("考试名称不能为空")
        return grade, className, exam_name
    return grade, className


def _require_grade(grade: str) -> str:
    """校验年级非空（聊天作用域：班级可选，空 = 整个年级）"""
    grade = (grade or "").strip()
    if not grade:
        raise BadRequestException("年级不能为空")
    return grade


@router.post("/upload", response_model=UploadResponse, summary="上传成绩单")
async def upload_grade_document(
    memoryId: str = Form(..., description="前端生成的会话 ID"),
    grade: str = Form(..., description="年级，如：高一"),
    className: str = Form(..., description="班级，如：3班"),
    examName: str = Form(..., description="考试名称，如：期中考试（同班同名考试重复上传视为覆盖）"),
    file: UploadFile = File(..., description="成绩单文件（PDF / .xlsx / .xls）")
) -> UploadResponse:
    """上传成绩文档到（年级+班级）桶，考试名称用于区分同桶多份成绩单

    使用示例（curl）：
        curl -X POST http://127.0.0.1:8000/ai/upload \
          -F "memoryId=session-001" \
          -F "grade=高一" \
          -F "className=3班" \
          -F "examName=期中考试" \
          -F "file=@高一3班期中.xlsx"
    """
    if not memoryId or memoryId.isspace():
        raise BadRequestException("memoryId 不能为空")
    grade, className, examName = _require_scope(grade, className, examName)
    try:
        extracted_text = grade_document_service.upload_and_store(grade, className, examName, file)
        length = len(extracted_text) if extracted_text else 0

        analyzer = grade_document_service.get_analyzer(grade, className)
        student_count = len(analyzer.student_names(exam=examName)) if analyzer else 0

        return UploadResponse(
            success=True,
            message=f"成绩单上传成功（{student_count}名学生），可在该班级会话中请求分析",
            textLength=length,
            grade=grade,
            className=className,
            examName=examName,
            bucketId=bucket_key(grade, className),
        )
    except ValueError as e:
        raise BadRequestException(str(e))


@router.get("/chat", response_model=ChatResponse, summary="成绩分析对话（非流式）")
async def chat(
    memoryId: str = Query(..., description="会话 ID"),
    message: str = Query(..., description="用户问题"),
    grade: str = Query(..., description="年级，如：高一"),
    className: str = Query("", description="班级（可选）：如 3班；为空时范围为整个年级，支持跨班对比")
) -> ChatResponse:
    """非流式对话：检索与分析作用于（年级+班级）桶；班级为空时为整个年级范围（跨班对比）

    使用示例：
        GET /ai/chat?memoryId=session-001&message=各科平均分是多少&grade=高一&className=3班
        GET /ai/chat?memoryId=session-001&message=对比3班和5班的语文平均分&grade=高一
    """
    if not memoryId or memoryId.isspace():
        raise BadRequestException("memoryId 不能为空")
    if not message or message.isspace():
        raise BadRequestException("message 不能为空")
    grade = _require_grade(grade)
    className = (className or "").strip()

    analyzer = grade_document_service.get_analyzer(grade, className or None)

    def search_fn(q):
        return grade_document_service.get_relevant_content(grade, className or None, q)

    try:
        full_text = await consultant_service.chat(memoryId, message, analyzer, search_fn)
        return ChatResponse(status=1, message="成功", data=full_text)
    except Exception as e:
        return ChatResponse(status=0, message=str(e), data=None)


@router.get("/chat/stream", summary="成绩分析对话（SSE 流式）")
async def chat_stream(
    memoryId: str = Query(..., description="会话 ID"),
    message: str = Query(..., description="用户问题"),
    grade: str = Query(..., description="年级，如：高一"),
    className: str = Query("", description="班级（可选）：如 3班；为空时范围为整个年级，支持跨班对比")
):
    """SSE 流式对话：检索与分析作用于（年级+班级）桶；班级为空时为整个年级范围（跨班对比）

    使用示例：
        GET /ai/chat/stream?memoryId=session-001&message=分析班级整体情况&grade=高一&className=3班

    返回格式：text/event-stream，逐行 `data: {"token": "..."}`，结束时输出 `data: [DONE]`。
    """
    if not memoryId or memoryId.isspace():
        raise BadRequestException("memoryId 不能为空")
    if not message or message.isspace():
        raise BadRequestException("message 不能为空")
    grade = _require_grade(grade)
    className = (className or "").strip()

    analyzer = grade_document_service.get_analyzer(grade, className or None)

    def search_fn(q):
        return grade_document_service.get_relevant_content(grade, className or None, q)

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


@router.get("/buckets", response_model=BucketListResponse, summary="列出已有数据桶")
async def list_buckets() -> BucketListResponse:
    """列出所有（年级+班级）桶及其考试文档

    使用示例：GET /ai/buckets
    """
    buckets = grade_document_service.list_buckets()
    infos = []
    for b in buckets:
        infos.append(BucketInfo(
            grade=b.get("grade", ""),
            className=b.get("className", ""),
            bucketId=b.get("bucketId", ""),
            documents=[DocumentInfo(**d) for d in b.get("docs", [])],
        ))
    return BucketListResponse(success=True, buckets=infos)


@router.delete("/document", response_model=SessionResponse, summary="删除单份考试文档")
async def delete_document(
    grade: str = Query(..., description="年级，如：高一"),
    className: str = Query(..., description="班级，如：3班"),
    examName: str = Query(..., description="考试名称，如：期中考试"),
) -> SessionResponse:
    """删除桶内单份考试文档

    使用示例：
        DELETE /ai/document?grade=高一&className=3班&examName=期中考试
    """
    grade, className, examName = _require_scope(grade, className, examName)
    grade_document_service.delete_document(grade, className, examName)
    return SessionResponse(success=True, message="成绩文档已删除")


@router.delete("/bucket", response_model=SessionResponse, summary="删除整个（年级+班级）桶")
async def delete_bucket(
    grade: str = Query(..., description="年级，如：高一"),
    className: str = Query(..., description="班级，如：3班"),
) -> SessionResponse:
    """删除整个（年级+班级）桶及其全部考试文档

    使用示例：DELETE /ai/bucket?grade=高一&className=3班
    """
    grade, className = _require_scope(grade, className)
    grade_document_service.delete_bucket(grade, className)
    return SessionResponse(success=True, message="该年级班级数据已删除")


@router.delete("/session", response_model=SessionResponse, summary="关闭会话（清除聊天记忆）")
async def close_session(memoryId: str = Query(..., description="会话 ID")) -> SessionResponse:
    """关闭会话：只清除聊天记忆；桶数据可能被多个会话共享，不再删除

    使用示例：DELETE /ai/session?memoryId=session-001
    """
    if not memoryId or memoryId.isspace():
        raise BadRequestException("memoryId 不能为空")
    redis_chat_memory_store.delete_messages(memoryId)
    consultant_service.delete_memory(memoryId)
    return SessionResponse(success=True, message="会话数据已清除")

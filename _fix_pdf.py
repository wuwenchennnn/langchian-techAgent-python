import os
base = r"D:\Python Project\langchain4j-techAgent-python"
path = os.path.join(base, "service", "grade_document_service.py")

new_content = '''from typing import Optional

import io
import PyPDF2

from rag import TextSplitter, Retriever
from repository.redis_grade_document_store import RedisGradeDocumentStore


class GradeDocumentService:
    """成绩文档服务：负责 PDF 解析与 RAG 流程编排"""

    # PDF 文件魔数（前 5 字节必须以此开头）
    PDF_MAGIC = b"%PDF-"

    def __init__(self):
        self.document_store = RedisGradeDocumentStore()
        self.splitter = TextSplitter()
        self.retriever = Retriever()

    def upload_and_store(self, memory_id: str, file) -> str:
        if not file:
            raise ValueError("文件不能为空")

        # 校验文件扩展名
        filename = getattr(file, "filename", "")
        if filename and not filename.lower().endswith(".pdf"):
            raise ValueError(f"仅支持 PDF 文件，当前文件: {filename}")

        # 读取文件内容
        file.file.seek(0)
        file_content = file.file.read()

        # 校验 PDF 魔数
        if not file_content or not file_content.startswith(self.PDF_MAGIC):
            raise ValueError("文件不是有效的 PDF 格式，请上传正确的 PDF 文件")

        extracted_text = self._extract_text_from_pdf(file_content)
        self.document_store.store_document(memory_id, extracted_text)

        chunks = self.splitter.split(extracted_text)
        if chunks:
            vectors = self.retriever.embed_documents(chunks)
            chunk_records = [
                {
                    "index": index,
                    "content": chunk,
                    "embedding": vector,
                }
                for index, (chunk, vector) in enumerate(zip(chunks, vectors))
            ]
            self.document_store.store_chunks(memory_id, chunk_records)

        return extracted_text

    def get_relevant_content(self, memory_id: str, message: str) -> Optional[str]:
        chunks = self.document_store.get_chunks(memory_id)
        if not chunks:
            return self.document_store.get_document(memory_id)

        return self.retriever.retrieve(message, chunks)

    def delete(self, memory_id: str):
        self.document_store.delete_document(memory_id)

    def _extract_text_from_pdf(self, pdf_content: bytes) -> str:
        text = ""
        try:
            reader = PyPDF2.PdfReader(io.BytesIO(pdf_content))
            for page_num in range(len(reader.pages)):
                page = reader.pages[page_num]
                page_text = page.extract_text() or ""
                text += page_text + "\n"
        except Exception as e:
            raise ValueError(f"PDF解析失败: {str(e)}")
        return text.strip()
'''

with open(path, "w", encoding="utf-8-sig") as f:
    f.write(new_content)

print("Fixed: added PDF validation (magic bytes + extension check)")

from typing import Optional

import io
import logging
import PyPDF2
import openpyxl
import xlrd

from rag import TextSplitter, Retriever
from repository.redis_grade_document_store import RedisGradeDocumentStore

logger = logging.getLogger(__name__)


class GradeDocumentService:
    """成绩文档服务：负责 PDF/Excel 解析与 RAG 流程编排"""

    PDF_MAGIC = b"%PDF-"
    XLSX_MAGIC = b"PK\x03\x04"

    SUPPORTED_EXTENSIONS = {".pdf", ".xlsx", ".xls"}

    def __init__(self):
        self.document_store = RedisGradeDocumentStore()
        self.splitter = TextSplitter()
        self.retriever = Retriever()

    def upload_and_store(self, memory_id: str, file) -> str:
        if not file:
            raise ValueError("文件不能为空")

        filename = getattr(file, "filename", "")
        if filename:
            ext = filename.lower()
            dot_idx = ext.rfind(".")
            ext = ext[dot_idx:] if dot_idx != -1 else ""
            if ext not in self.SUPPORTED_EXTENSIONS:
                raise ValueError(f"仅支持 PDF / Excel（.xlsx / .xls）文件，当前文件: {filename}")

        file.file.seek(0)
        file_content = file.file.read()

        if not file_content:
            raise ValueError("文件内容为空")

        if file_content.startswith(self.PDF_MAGIC):
            extracted_text = self._extract_text_from_pdf(file_content)
        elif file_content.startswith(self.XLSX_MAGIC):
            extracted_text = self._extract_text_from_xlsx(file_content)
        else:
            ext = filename.lower() if filename else ""
            dot_idx = ext.rfind(".")
            ext = ext[dot_idx:] if dot_idx != -1 else ""
            if ext == ".xls":
                extracted_text = self._extract_text_from_xls(file_content)
            else:
                raise ValueError("无法识别的文件格式，请上传 PDF 或 Excel 文件")

        self.document_store.store_document(memory_id, extracted_text)

        chunks = self.splitter.split(extracted_text)
        if chunks:
            try:
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
            except Exception as e:
                logger.warning("Embedding 失败（将回退为全文检索）: %s", e)

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

    def _extract_text_from_xlsx(self, xlsx_content: bytes) -> str:
        text_parts = []
        try:
            wb = openpyxl.load_workbook(io.BytesIO(xlsx_content), read_only=True, data_only=True)
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                text_parts.append(f"【工作表: {sheet_name}】")
                for row in ws.iter_rows(values_only=True):
                    row_text = "\t".join(
                        str(cell) if cell is not None else ""
                        for cell in row
                    )
                    if row_text.strip():
                        text_parts.append(row_text)
            wb.close()
        except Exception as e:
            raise ValueError(f"Excel(.xlsx)解析失败: {str(e)}")
        return "\n".join(text_parts).strip()

    def _extract_text_from_xls(self, xls_content: bytes) -> str:
        text_parts = []
        try:
            wb = xlrd.open_workbook(file_contents=xls_content)
            for sheet_idx in range(wb.nsheets):
                ws = wb.sheet_by_index(sheet_idx)
                text_parts.append(f"【工作表: {ws.name}】")
                for row_idx in range(ws.nrows):
                    row_values = ws.row_values(row_idx)
                    row_text = "\t".join(
                        str(cell) if cell != "" else ""
                        for cell in row_values
                    )
                    if row_text.strip():
                        text_parts.append(row_text)
        except Exception as e:
            raise ValueError(f"Excel(.xls)解析失败: {str(e)}")
        return "\n".join(text_parts).strip()
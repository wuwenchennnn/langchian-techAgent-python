from typing import Optional

import io
import logging
import PyPDF2
import openpyxl
import xlrd

from rag import TextSplitter, GradeTextSplitter, Retriever, HybridRetriever
from rag.reranker import create_reranker
from repository.redis_grade_document_store import RedisGradeDocumentStore
from service.grade_analyzer import GradeAnalyzer

logger = logging.getLogger(__name__)


class GradeDocumentService:
    """成绩文档服务：负责 PDF/Excel 解析、RAG 流程编排与结构化分析"""

    PDF_MAGIC = b"%PDF-"
    XLSX_MAGIC = b"PK\x03\x04"

    SUPPORTED_EXTENSIONS = {".pdf", ".xlsx", ".xls"}

    def __init__(self):
        self.document_store = RedisGradeDocumentStore()
        self.splitter = TextSplitter()
        self.grade_splitter = GradeTextSplitter()
        self.vector_retriever = Retriever()
        self.reranker, self._reranker_type = create_reranker()
        logger.info("[重排序器] 当前使用: %s", self._reranker_type)
        self._analyzers: dict[str, GradeAnalyzer] = {}
        self._hybrid_retrievers: dict[str, HybridRetriever] = {}

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

        # 结构化分析
        analyzer = GradeAnalyzer()
        records = analyzer.parse(extracted_text)
        logger.info("解析到 %d 条成绩记录，%d 名学生，%d 门科目",
                     len(records), len(analyzer._student_names), len(analyzer._subjects))
        self._analyzers[memory_id] = analyzer

        self.document_store.store_document(memory_id, extracted_text)

        # 优先使用结构化语义分块，回退到固定分块
        if records and analyzer._student_names:
            chunks = self.grade_splitter.split_by_records(
                records, analyzer._student_names, analyzer._subjects
            )
        else:
            chunks = self.splitter.split(extracted_text)

        if chunks:
            try:
                vectors = self.vector_retriever.embed_documents(chunks)
                chunk_records = [
                    {
                        "index": index,
                        "content": chunk,
                        "embedding": vector,
                    }
                    for index, (chunk, vector) in enumerate(zip(chunks, vectors))
                ]
                self.document_store.store_chunks(memory_id, chunk_records)

                # 构建混合检索引擎的 BM25 索引
                hybrid = HybridRetriever(self.vector_retriever)
                hybrid.index_chunks(chunk_records)
                self._hybrid_retrievers[memory_id] = hybrid
                logger.info("混合检索索引已就绪，chunk 数=%d", len(chunk_records))

            except Exception as e:
                logger.warning("Embedding 失败（将回退为全文检索）: %s", e)

        return extracted_text

    def get_analyzer(self, memory_id: str) -> Optional[GradeAnalyzer]:
        """获取指定会话的分析器"""
        return self._analyzers.get(memory_id)

    def get_relevant_content(self, memory_id: str, message: str) -> Optional[str]:
        chunks = self.document_store.get_chunks(memory_id)
        if not chunks:
            return self.document_store.get_document(memory_id)

        # 优先使用混合检索（向量 + BM25 + 重排序）
        hybrid = self._hybrid_retrievers.get(memory_id)
        if hybrid:
            try:
                # 混合检索召回候选池（放大 3 倍）
                candidates, scored = hybrid.retrieve(
                    message,
                    top_k=None,
                    candidate_multiplier=3,
                )
                if scored:
                    # 重排序（BGE 或 LLM，由工厂自动选择）
                    reranked = self.reranker.rerank(message, scored)
                    contents = [c.get("content", "") for c in reranked]
                    if contents:
                        logger.info(
                            "[混合检索+重排序] memory_id=%s | 候选=%d → 返回=%d | 引擎=%s",
                            memory_id, len(scored), len(contents), self._reranker_type
                        )
                        return "\n\n---\n\n".join(contents)

            except Exception as e:
                logger.warning("混合检索失败，回退到纯向量检索: %s", e)

        # 兜底：纯向量检索
        return self.vector_retriever.retrieve(message, chunks)

    def delete(self, memory_id: str):
        self.document_store.delete_document(memory_id)
        self._analyzers.pop(memory_id, None)
        self._hybrid_retrievers.pop(memory_id, None)

    # ---------- PDF / Excel 解析 ----------
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
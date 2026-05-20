import math
from typing import List, Optional

import PyPDF2
from langchain_openai import OpenAIEmbeddings

from config.settings import settings
from repository.redis_grade_document_store import RedisGradeDocumentStore


class GradeDocumentService:
    def __init__(self):
        self.document_store = RedisGradeDocumentStore()
        self.embeddings = OpenAIEmbeddings(
            model=settings.embedding_model_name,
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
        )

    def upload_and_store(self, memory_id: str, file) -> str:
        if not file:
            raise ValueError("文件不能为空")

        file_content = file.file.read()
        extracted_text = self._extract_text_from_pdf(file_content)
        self.document_store.store_document(memory_id, extracted_text)

        chunks = self._split_text(extracted_text)
        if chunks:
            vectors = self.embeddings.embed_documents(chunks)
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

        query_embedding = self.embeddings.embed_query(message)
        scored_chunks = []
        for chunk in chunks:
            score = self._cosine_similarity(query_embedding, chunk.get("embedding", []))
            scored_chunks.append((score, chunk))

        scored_chunks.sort(key=lambda item: item[0], reverse=True)
        selected_chunks = [
            item[1]["content"]
            for item in scored_chunks[:settings.rag_top_k]
            if item[1].get("content")
        ]
        if not selected_chunks:
            return None

        return "\n\n---\n\n".join(selected_chunks)

    def delete(self, memory_id: str):
        self.document_store.delete_document(memory_id)

    def _extract_text_from_pdf(self, pdf_content: bytes) -> str:
        text = ""
        try:
            reader = PyPDF2.PdfReader(pdf_content)
            for page_num in range(len(reader.pages)):
                page = reader.pages[page_num]
                page_text = page.extract_text() or ""
                text += page_text + "\n"
        except Exception as e:
            raise ValueError(f"PDF解析失败: {str(e)}")
        return text.strip()

    def _split_text(self, text: str) -> List[str]:
        cleaned_text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if not cleaned_text:
            return []

        chunk_size = max(settings.rag_chunk_size, 100)
        overlap = min(max(settings.rag_chunk_overlap, 0), chunk_size - 1)
        chunks = []
        start = 0

        while start < len(cleaned_text):
            end = min(start + chunk_size, len(cleaned_text))
            chunk = cleaned_text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end == len(cleaned_text):
                break
            start = end - overlap

        return chunks

    @staticmethod
    def _cosine_similarity(left: List[float], right: List[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0

        dot_product = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0

        return dot_product / (left_norm * right_norm)

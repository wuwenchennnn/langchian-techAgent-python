import math
from typing import List, Optional

from langchain_openai import OpenAIEmbeddings

from config.settings import settings


class Retriever:
    """向量检索器：负责 Embedding 生成、余弦相似度计算和 top-k 片段召回"""

    def __init__(self, embeddings: OpenAIEmbeddings = None):
        self.embeddings = embeddings or OpenAIEmbeddings(
            model=settings.embedding_model_name,
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
        )

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """批量生成文档向量"""
        return self.embeddings.embed_documents(texts)

    def embed_query(self, query: str) -> List[float]:
        """生成查询向量"""
        return self.embeddings.embed_query(query)

    def retrieve(self, query: str, chunks: List[dict], top_k: int = None) -> Optional[str]:
        """
        基于查询向量与 chunk 向量的余弦相似度，召回 top-k 个最相关片段

        Args:
            query: 用户查询文本
            chunks: chunk 列表，每项含 content 和 embedding
            top_k: 召回数量，默认使用 settings.rag_top_k

        Returns:
            拼接后的相关文本片段，无结果时返回 None
        """
        if not chunks:
            return None

        top_k = top_k or settings.rag_top_k
        query_embedding = self.embed_query(query)

        scored_chunks = []
        for chunk in chunks:
            score = self._cosine_similarity(query_embedding, chunk.get("embedding", []))
            scored_chunks.append((score, chunk))

        scored_chunks.sort(key=lambda item: item[0], reverse=True)
        selected_chunks = [
            item[1]["content"]
            for item in scored_chunks[:top_k]
            if item[1].get("content")
        ]

        if not selected_chunks:
            return None

        return "\n\n---\n\n".join(selected_chunks)

    @staticmethod
    def _cosine_similarity(left: List[float], right: List[float]) -> float:
        """计算两个向量的余弦相似度"""
        if not left or not right or len(left) != len(right):
            return 0.0

        dot_product = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0

        return dot_product / (left_norm * right_norm)

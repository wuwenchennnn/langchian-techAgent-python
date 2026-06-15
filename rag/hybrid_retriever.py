"""混合检索引擎：BM25 关键词检索 + 向量语义检索 + RRF 融合"""

import math
import re
from collections import defaultdict
from typing import List, Optional, Tuple

from rag.retriever import Retriever

# 英文/数字分隔符（字符类末尾的 - 是字面量）
_NON_CHINESE_SPLIT = re.compile(r"""[,\s，。.!!?？:：;；、()（）\[\]【】""''+=—-]+""")


class BM25Scorer:
    """轻量级 BM25 评分器，基于字符级 bigram 分词，适配中文文本"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.documents: List[str] = []
        self.doc_terms: List[dict] = []
        self.doc_lengths: List[int] = []
        self.avg_doc_length: float = 0.0
        self.df: dict = defaultdict(int)
        self.idf: dict = {}
        self._built = False

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """中文按字符 bigram 切分，英文/数字按分隔符切分"""
        tokens = []
        segments = re.split(r"([\u4e00-\u9fff]+)", text)
        for seg in segments:
            if not seg.strip():
                continue
            if re.match(r"[\u4e00-\u9fff]+", seg):
                for i in range(len(seg) - 1):
                    tokens.append(seg[i:i+2])
                if len(seg) == 1:
                    tokens.append(seg)
            else:
                for token in _NON_CHINESE_SPLIT.split(seg):
                    token = token.strip().lower()
                    if token:
                        tokens.append(token)
        return tokens

    def index(self, documents: List[str]):
        """构建 BM25 索引"""
        self.documents = documents
        self.doc_terms = []
        self.doc_lengths = []
        self.df.clear()

        for doc in documents:
            tokens = self._tokenize(doc)
            term_freq = defaultdict(int)
            for t in tokens:
                term_freq[t] += 1
            self.doc_terms.append(dict(term_freq))
            self.doc_lengths.append(len(tokens))
            for t in set(tokens):
                self.df[t] += 1

        total_docs = len(documents)
        self.avg_doc_length = sum(self.doc_lengths) / max(total_docs, 1)
        self.idf = {
            t: math.log((total_docs - freq + 0.5) / (freq + 0.5) + 1.0)
            for t, freq in self.df.items()
        }
        self._built = True

    def score_batch(self, query: str) -> List[float]:
        """对已索引的所有文档计算 BM25 得分"""
        if not self._built:
            return [0.0] * len(self.documents)

        query_tokens = self._tokenize(query)
        scores = []
        for i, term_freq in enumerate(self.doc_terms):
            score = 0.0
            doc_len = self.doc_lengths[i]
            for t in query_tokens:
                if t not in self.idf:
                    continue
                tf = term_freq.get(t, 0)
                idf_val = self.idf[t]
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / max(self.avg_doc_length, 1))
                score += idf_val * numerator / denominator
            scores.append(score)
        return scores


class HybridRetriever:
    """混合检索器：向量语义 + BM25 关键词 + RRF 融合"""

    RRF_K = 60

    def __init__(self, vector_retriever: Retriever = None):
        self.vector_retriever = vector_retriever or Retriever()
        self.bm25 = BM25Scorer()
        self.chunks: List[dict] = []
        self._indexed = False

    def index_chunks(self, chunks: List[dict]):
        """构建 BM25 索引"""
        self.chunks = chunks
        contents = [c.get("content", "") for c in chunks]
        self.bm25.index(contents)
        self._indexed = True

    def retrieve(
        self,
        query: str,
        top_k: int = None,
        candidate_multiplier: int = 3,
    ) -> Tuple[List[str], List[dict]]:
        """混合检索：RRF 融合向量与关键词得分"""
        from config.settings import settings
        top_k = top_k or settings.rag_top_k

        if not self.chunks:
            return [], []

        query_embedding = self.vector_retriever.embed_query(query)

        # -- 向量得分 --
        vector_scores = []
        for c in self.chunks:
            score = Retriever._cosine_similarity(query_embedding, c.get("embedding", []))
            vector_scores.append((score, c))

        # -- BM25 得分 --
        bm25_scores = self.bm25.score_batch(query)

        # -- RRF 融合 --
        candidate_count = min(top_k * candidate_multiplier, len(self.chunks))

        vector_sorted = sorted(enumerate(vector_scores), key=lambda x: x[1][0], reverse=True)
        bm25_sorted = sorted(enumerate(bm25_scores), key=lambda x: x[1], reverse=True)

        vector_rank = {idx: r + 1 for r, (idx, _) in enumerate(vector_sorted)}
        bm25_rank = {idx: r + 1 for r, (idx, _) in enumerate(bm25_sorted)}

        candidate_indices = set()
        for idx, _ in vector_sorted[:candidate_count]:
            candidate_indices.add(idx)
        for idx, _ in bm25_sorted[:candidate_count]:
            candidate_indices.add(idx)

        rrf_scores = []
        for idx in candidate_indices:
            v_rank = vector_rank.get(idx, len(self.chunks))
            b_rank = bm25_rank.get(idx, len(self.chunks))
            rrf = 1.0 / (self.RRF_K + v_rank) + 1.0 / (self.RRF_K + b_rank)
            tiebreaker = vector_scores[idx][0]
            rrf_scores.append((rrf, tiebreaker, self.chunks[idx]))

        rrf_scores.sort(key=lambda x: (x[0], x[1]), reverse=True)

        selected = rrf_scores[:top_k]
        contents = [item[2].get("content", "") for item in selected]
        scored_chunks = [
            {"content": item[2].get("content", ""), "score": item[0], "embedding": item[2].get("embedding", [])}
            for item in selected
        ]
        return contents, scored_chunks

    def retrieve_as_text(self, query: str, top_k: int = None) -> Optional[str]:
        """混合检索，返回拼接后的文本片段"""
        contents, _ = self.retrieve(query, top_k)
        if not contents:
            return None
        return "\n\n---\n\n".join(contents)
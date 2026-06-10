from typing import List

from config.settings import settings


class TextSplitter:
    """文本切块器：按固定大小 + 重叠窗口将长文本切分为多个 chunk"""

    def __init__(self, chunk_size: int = None, chunk_overlap: int = None):
        self.chunk_size = max(chunk_size or settings.rag_chunk_size, 100)
        self.chunk_overlap = min(max(chunk_overlap or settings.rag_chunk_overlap, 0), self.chunk_size - 1)

    def split(self, text: str) -> List[str]:
        """将文本切分为多个 chunk"""
        cleaned_text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if not cleaned_text:
            return []

        chunks = []
        start = 0

        while start < len(cleaned_text):
            end = min(start + self.chunk_size, len(cleaned_text))
            chunk = cleaned_text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end == len(cleaned_text):
                break
            start = end - self.chunk_overlap

        return chunks

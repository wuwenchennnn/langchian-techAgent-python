"""重排序器：BGE-Reranker-v2-M3 精排 + LLM 重排兜底"""

import json
import logging
from typing import List, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from config.settings import settings

logger = logging.getLogger(__name__)

# ---------- LLM 重排序器（兜底方案）----------

RERANK_SYSTEM_PROMPT = (
    "你是一个专业的文档相关性评估助手。"
    "你的任务是根据用户查询，评估每段文档内容与查询的相关程度，并给出 0-10 的评分。\n"
    "评分标准：\n"
    "- 10 分：完全匹配，直接回答问题\n"
    "- 7-9 分：高度相关，包含关键信息\n"
    "- 4-6 分：部分相关，有一定参考价值\n"
    "- 1-3 分：弱相关，仅包含个别关键词\n"
    "- 0 分：完全不相关\n"
    "请严格只返回 JSON 数组，格式：[分数1, 分数2, ...]，不要包含任何其他文字。"
)


class LLMReranker:
    """基于 LLM 的片段重排序器"""

    def __init__(self, llm: ChatOpenAI = None):
        self.llm = llm or ChatOpenAI(
            model=settings.openai_model_name,
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            temperature=0.0,
        )

    def rerank(
        self,
        query: str,
        candidates: List[dict],
        batch_size: int = 5,
        top_k: int = None,
    ) -> List[dict]:
        """对候选片段进行 LLM 打分重排序"""
        if not candidates:
            return candidates

        top_k = top_k or len(candidates)
        contents = [c.get("content", "") for c in candidates]

        all_scores = []
        for i in range(0, len(contents), batch_size):
            batch = contents[i:i + batch_size]
            scores = self._score_batch(query, batch)
            all_scores.extend(scores)

        scored = list(zip(all_scores, candidates))
        scored.sort(key=lambda x: x[0], reverse=True)

        result = [item[1] for item in scored[:top_k]]
        logger.info(
            "[LLM重排序] 候选=%d → 返回=%d | 最高分=%.1f | 最低分=%.1f",
            len(candidates), len(result),
            scored[0][0] if scored else 0,
            scored[-1][0] if scored else 0,
        )
        return result

    def _score_batch(self, query: str, documents: List[str]) -> List[float]:
        """对一批文档逐条打分"""
        if not documents:
            return []

        doc_list = "\n\n".join(
            f"--- 文档 {j+1} ---\n{doc[:500]}"
            for j, doc in enumerate(documents)
        )
        user_prompt = (
            f"用户查询：{query}\n\n"
            f"以下是 {len(documents)} 段文档，请分别为每段文档与查询的相关性打分（0-10）：\n\n"
            f"{doc_list}"
        )

        messages = [
            SystemMessage(content=RERANK_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        try:
            response = self.llm.invoke(messages)
            scores = self._parse_scores(response.content, len(documents))
        except Exception as e:
            logger.warning("LLM 重排序失败，返回默认分数: %s", e)
            scores = [5.0] * len(documents)

        return scores

    @staticmethod
    def _parse_scores(raw: str, expected_count: int) -> List[float]:
        """解析 LLM 返回的分数数组"""
        try:
            scores = json.loads(raw)
            if isinstance(scores, list):
                return [float(s) for s in scores[:expected_count]]
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        import re
        match = re.search(r'\[[\d.,\s]+\]', raw)
        if match:
            try:
                scores = json.loads(match.group())
                if isinstance(scores, list):
                    return [float(s) for s in scores[:expected_count]]
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        logger.warning("无法解析重排序分数，使用默认值。原始响应: %s", raw[:200])
        return [5.0] * expected_count


# ---------- BGE-Reranker 专用精排模型 ----------

class BGEReranker:
    """基于 BGE-Reranker-v2-M3 的专用重排序器（本地推理，零 API 成本）"""

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3", use_fp16: bool = True):
        self.model_name = model_name
        self._model = None
        self._use_fp16 = use_fp16
        self._init_error: Optional[str] = None

    @property
    def is_available(self) -> bool:
        """模型是否加载成功"""
        return self._model is not None

    @property
    def init_error(self) -> Optional[str]:
        """加载失败原因"""
        return self._init_error

    def _lazy_init(self):
        """延迟加载模型（首次调用时才加载，避免启动阻塞）"""
        if self._model is not None:
            return
        if self._init_error is not None:
            return

        try:
            from FlagEmbedding import FlagReranker
            self._model = FlagReranker(self.model_name, use_fp16=self._use_fp16)
            logger.info(
                "[BGE-Reranker] 模型加载成功: %s (fp16=%s)",
                self.model_name, self._use_fp16
            )
        except ImportError:
            self._init_error = "FlagEmbedding 未安装，请执行: pip install FlagEmbedding"
            logger.warning("[BGE-Reranker] %s", self._init_error)
        except Exception as e:
            self._init_error = f"BGE 模型加载失败: {e}"
            logger.warning("[BGE-Reranker] %s", self._init_error)

    def rerank(
        self,
        query: str,
        candidates: List[dict],
        top_k: int = None,
    ) -> List[dict]:
        """
        对候选片段进行 BGE 打分重排序

        Args:
            query: 用户查询
            candidates: 候选片段列表，每项含 content
            top_k: 最终返回数量，默认全量

        Returns:
            按分数降序排列的候选片段
        """
        if not candidates:
            return candidates

        self._lazy_init()
        if self._model is None:
            raise RuntimeError(self._init_error or "BGE 模型未加载")

        top_k = top_k or len(candidates)
        contents = [c.get("content", "") for c in candidates]

        # 构建 (query, doc) 对，批量计算
        pairs = [[query, doc[:512]] for doc in contents]
        scores = self._model.compute_score(pairs, normalize=True)

        # 处理单个结果的情况
        if isinstance(scores, float):
            scores = [scores]

        scored = list(zip(scores, candidates))
        scored.sort(key=lambda x: x[0], reverse=True)
        result = [item[1] for item in scored[:top_k]]

        logger.info(
            "[BGE重排序] 候选=%d → 返回=%d | 最高分=%.3f | 最低分=%.3f | 耗时≈%.0fms",
            len(candidates), len(result),
            scored[0][0] if scored else 0,
            scored[-1][0] if scored else 0,
            len(candidates) * 15,  # BGE 每对约 15ms
        )
        return result


# ---------- 工厂：自动选择最优重排序器 ----------

def create_reranker(prefer_bge: bool = True):
    """
    创建重排序器，优先使用 BGE 本地模型，失败则回退 LLM

    Args:
        prefer_bge: 是否优先使用 BGE

    Returns:
        (reranker_instance, reranker_type_name)
    """
    if prefer_bge:
        bge = BGEReranker()
        try:
            bge._lazy_init()
        except Exception:
            pass

        if bge.is_available:
            return bge, "BGE-Reranker-v2-M3"

        logger.info("[重排序] BGE 不可用（%s），回退到 LLM 重排序", bge.init_error)

    llm = LLMReranker()
    return llm, "LLM"
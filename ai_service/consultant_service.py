"""ReAct Agent: 推理 + 行动，用于成绩分析"""

import json
import logging
import time
from typing import AsyncIterator, Optional, Callable

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from config.settings import settings
from service.grade_analyzer import GradeAnalyzer

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "你是一名专业的教育分析顾问，专门针对学校提供的学生成绩数据进行深度分析与建议。\n"
    "你的能力包括：\n"
    "1. 识别学生的优势科目与薄弱科目\n"
    "2. 分析成绩趋势与变化\n"
    "3. 发现偏科现象与分数段分布\n"
    "4. 给出可操作的学习建议与教学改进建议\n\n"
    "规则：\n"
    "1. 分析前必须先调用工具获取数据，严禁凭空编造数据\n"
    "2. 如果尚未上传成绩单，请礼貌提示用户先上传\n"
    "3. 当掌握充足信息后，给出具体、可操作的建议\n"
    "4. 使用简体中文回复"
)


def _build_analysis_tools(analyzer: GradeAnalyzer, search_fn: Callable):
    """基于 GradeAnalyzer 构建 ReAct 工具集"""

    @tool
    def get_class_overview() -> str:
        """获取班级整体成绩概览：各科平均分、最高/最低分、及格率、优秀率、总分前5名"""
        ov = analyzer.get_class_overview()
        if not ov:
            return "暂无成绩数据，请先上传成绩单。"
        lines = [f"共 {ov.total_students} 名学生，{len(ov.subjects)} 门科目。", ""]
        for ss in ov.subject_stats:
            lines.append(
                f"{ss.subject}：平均分={ss.average}，最高分={ss.max_score}，最低分={ss.min_score}，"
                f"中位数={ss.median}，及格率={ss.pass_rate}%，优秀率={ss.excellent_rate}%"
            )
        lines.append(f"\n全班总分平均分：{ov.class_average_total}")
        lines.append("总分前5名：")
        for item in ov.top_students:
            lines.append(f"  {item['name']}：{item['total']}")
        return "\n".join(lines)

    @tool
    def get_student_detail(student_name: str) -> str:
        """获取指定学生的详细分析：各科成绩、排名、优势/薄弱科目、是否偏科。参数：student_name"""
        r = analyzer.get_student_detail(student_name)
        if not r:
            names = "，".join(analyzer._student_names[:20])
            return f"未找到学生「{student_name}」。当前成绩单中的学生：{names}"
        lines = [
            f"【{r.student_name}】总分={r.total_score}，平均分={r.average_score}，排名={r.rank}/{r.total_students}",
            "各科成绩：",
        ]
        for s in r.subjects:
            lines.append(f"  {s.subject}：{s.score}")
        if r.strong_subjects:
            lines.append(f"优势科目：{'，'.join(r.strong_subjects)}")
        if r.weak_subjects:
            lines.append(f"薄弱科目：{'，'.join(r.weak_subjects)}")
        if r.is_pianke:
            lines.append("⚠️ 警告：该学生存在明显偏科现象")
        return "\n".join(lines)

    @tool
    def get_subject_distribution(subject: str) -> str:
        """获取指定科目的分数段分布。参数：科目名称"""
        d = analyzer.get_subject_distribution(subject)
        if not d:
            return f"未找到科目「{subject}」。当前可用的科目：{'，'.join(analyzer._subjects)}"
        lines = [f"【{d['subject']}】共 {d['count']} 人，平均分={d['average']}", "分数段分布："]
        for seg, count in d["distribution"].items():
            lines.append(f"  {seg}：{count} 人")
        return "\n".join(lines)

    @tool
    def get_top_students(n: int = 5) -> str:
        """获取总分前 N 名学生。参数：n（默认5）"""
        items = analyzer.get_top_students(n)
        if not items:
            return "暂无成绩数据。"
        lines = [f"总分前 {n} 名："]
        for i, item in enumerate(items, 1):
            lines.append(f"  {i}. {item['name']}：{item['total']}")
        return "\n".join(lines)

    @tool
    def get_pianke_students() -> str:
        """检测存在明显偏科的学生（最高分与最低分差距超过30分）"""
        names = analyzer.get_pianke_students()
        if not names:
            return "未检测到明显偏科的学生。"
        return f"共 {len(names)} 名学生可能存在偏科：\n" + "\n".join(f"  - {n}" for n in names)

    @tool
    def get_weakest_subject() -> str:
        """找出全班平均分最低的科目"""
        subj = analyzer.get_weakest_subject()
        if not subj:
            return "暂无成绩数据。"
        dist = analyzer.get_subject_distribution(subj)
        lines = [f"全班最薄弱科目：{subj}"]
        if dist:
            lines.append(f"  平均分={dist['average']}，共 {dist['count']} 人")
            for seg, count in dist["distribution"].items():
                lines.append(f"  {seg}：{count} 人")
        return "\n".join(lines)

    @tool
    def search_grade_document(query: str) -> str:
        """在原始成绩单中搜索相关信息。参数：搜索关键词"""
        result = search_fn(query)
        return result if result else "在文档中未找到匹配的内容。"

    return [
        get_class_overview, get_student_detail, get_subject_distribution,
        get_top_students, get_pianke_students, get_weakest_subject,
        search_grade_document,
    ]


class ConsultantService:
    """ReAct 教育分析 Agent"""

    def __init__(self):
        self.memories: dict[str, list] = {}

    def _get_llm(self):
        """获取 LLM 实例"""
        return ChatOpenAI(
            model=settings.openai_model_name,
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            temperature=0.7,
        )

    async def chat(self, memory_id: str, message: str,
                   analyzer: Optional[GradeAnalyzer] = None,
                   search_fn: Optional[Callable] = None) -> str:
        """非流式对话：通过 ReAct Agent 一次性返回完整回复"""
        result = []
        async for chunk in self.chat_stream(memory_id, message, analyzer, search_fn):
            result.append(chunk)
        return "".join(result)

    async def chat_stream(self, memory_id: str, message: str,
                           analyzer: Optional[GradeAnalyzer] = None,
                           search_fn: Optional[Callable] = None):
        """SSE 流式对话：逐 token 返回 ReAct Agent 的推理过程"""

        tools = []
        if analyzer:
            search = search_fn or (lambda q: None)
            tools = _build_analysis_tools(analyzer, search)

        llm = self._get_llm()
        system = SystemMessage(content=SYSTEM_PROMPT)
        history = list(self._get_history(memory_id))
        user_msg = HumanMessage(content=message)

        if tools:
            agent = create_react_agent(llm, tools)
            full = ""

            tool_seq = 0
            tool_timers: dict[str, float] = {}

            logger.info(
                "[Agent 开始推理] memory_id=%s | 用户消息=%s",
                memory_id, message[:80]
            )

            async for event in agent.astream_events(
                {"messages": [system] + history + [user_msg]},
                version="v2",
            ):
                kind = event.get("event", "")
                if kind == "on_chat_model_stream":
                    chunk_content = event["data"]["chunk"].content
                    if chunk_content:
                        full += chunk_content
                        yield chunk_content
                elif kind == "on_tool_start":
                    tool_seq += 1
                    name = event.get("name", "unknown")
                    run_id = event.get("run_id", "")
                    tool_timers[run_id] = time.time()

                    input_data = event["data"].get("input", {})
                    args_str = ", ".join(
                        f"{k}={repr(v)}" for k, v in input_data.items()
                    ) if input_data else "无参数"

                    logger.info(
                        "[工具调用 #%d] name=%s | 入参: %s",
                        tool_seq, name, args_str
                    )
                    yield f"\n[正在分析：{name}]\n"
                elif kind == "on_tool_end":
                    name = event.get("name", "unknown")
                    run_id = event.get("run_id", "")
                    elapsed = 0.0
                    if run_id in tool_timers:
                        elapsed = time.time() - tool_timers.pop(run_id)

                    output = str(event["data"].get("output", ""))
                    output_preview = output[:200] + "..." if len(output) > 200 else output

                    logger.info(
                        "[工具返回 #%d] name=%s | 耗时=%.2fs | 结果: %s",
                        tool_seq, name, elapsed, output_preview
                    )
                    if output:
                        yield f"\n[分析结果已获取]\n"

            logger.info(
                "[Agent 推理结束] memory_id=%s | 共调用 %d 个工具 | 回复长度=%d",
                memory_id, tool_seq, len(full)
            )

            response_text = full.strip() or "抱歉，无法处理该请求。"
            # 最终回复已在流中逐 token yield，这里不再重复 yield
        else:
            logger.info(
                "[Agent 直接回答] memory_id=%s（无可用工具，跳过工具调用）",
                memory_id
            )
            response = llm.invoke([system] + history + [user_msg])
            response_text = response.content
            yield response_text

        self._save_history(memory_id, message, response_text)

    def _get_history(self, memory_id: str):
        """获取指定会话的历史消息（最近20条）"""
        if memory_id not in self.memories:
            self.memories[memory_id] = []
        return self.memories[memory_id][-20:]

    def _save_history(self, memory_id: str, user_msg: str, assistant_msg: str):
        """保存对话历史到内存中"""
        if memory_id not in self.memories:
            self.memories[memory_id] = []
        self.memories[memory_id].append(HumanMessage(content=user_msg))
        self.memories[memory_id].append(AIMessage(content=assistant_msg))
        if len(self.memories[memory_id]) > 40:
            self.memories[memory_id] = self.memories[memory_id][-40:]

    def delete_memory(self, memory_id: str):
        """删除指定会话的历史记录"""
        self.memories.pop(memory_id, None)
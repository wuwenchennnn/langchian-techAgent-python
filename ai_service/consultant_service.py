"""ReAct Agent: 推理 + 行动，用于成绩分析"""

import json
import logging
import time
from typing import AsyncIterator, Optional, Callable, Union

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from config.settings import settings
from service.bucket_analyzer import BucketAnalyzer
from service.chart_generator import ChartGenerator
from service.grade_scope_analyzer import GradeScopeAnalyzer
from repository.redis_chat_memory_store import RedisChatMemoryStore

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "你是一名专业的教育分析顾问，专门针对学校提供的学生成绩数据进行深度分析与建议。\n"
    "你的能力包括：\n"
    "1. 识别学生的优势科目与薄弱科目\n"
    "2. 分析成绩趋势与变化\n"
    "3. 发现偏科现象与分数段分布\n"
    "4. 给出可操作的学习建议与教学改进建议\n"
    "5. 当用户请求图表、趋势图、折线图、柱状图、雷达图或可视化时，调用 get_chart_data 生成图表数据\n\n"
    "规则：\n"
    "1. 分析前必须先调用工具获取数据，严禁凭空编造数据\n"
    "2. 如果尚未上传成绩单，请礼貌提示用户先上传\n"
    "3. 当掌握充足信息后，给出具体、可操作的建议\n"
    "4. 必须结合对话历史理解用户意图\n"
    "5. 生成图表后，用简短文字总结图表反映的关键信息\n"
    "6. 数据可能包含多次考试（如期中、期末、月考）。回答涉及具体数据时，必须注明考试名称\n"
    "7. 用户询问两次或多次考试的成绩对比、变化趋势时，调用 compare_exams 工具\n"
    "8. 分析工具均支持可选 exam 参数（考试名称），未指定时默认使用最近一次上传的考试；多班级（全年级）范围下，涉及班级的分析需通过 className 参数指定班级\n"
    "9. 检索片段会标注【年级班级·考试名】，引用时注意区分考试\n"
    "10. 用户询问不同班级之间的成绩对比时，必须调用 compare_classes 工具，回答注明班级与考试名称"
)


SUMMARY_SYSTEM_PROMPT = (
    "你是一名对话摘要助手。请把下面的对话内容压缩成简洁的中文要点摘要，"
    "保留：用户关注的问题主题、涉及的年级/班级/考试、已得出的关键结论与分析结果。"
    "不要编造原文没有的信息，控制在 200 字以内，直接输出摘要正文，不要添加其他说明。"
)


def _resolve_exam(analyzer: BucketAnalyzer, exam: str):
    """解析考试参数：空值返回 (None, None) 表示使用最近一次；未找到返回 (None, 错误信息)"""
    exam = (exam or "").strip()
    if not exam:
        return None, None
    resolved = analyzer.resolve_exam(exam)
    if resolved is None:
        available = "、".join(analyzer.list_exams()) or "（暂无）"
        return None, f"未找到考试「{exam}」。当前桶内的考试：{available}"
    return resolved, None


def _class_err(analyzer, className: str):
    """年级级作用域下解析班级；返回 (班级名 或 None, 错误信息 或 None)"""
    if not hasattr(analyzer, "resolve_class"):
        return None, None
    className = (className or "").strip()
    classes = analyzer.list_classes()
    if not className:
        if len(classes) == 1:
            return classes[0], None
        return None, f"请指定要分析的班级。当前年级下的班级：{'、'.join(classes) or '（暂无）'}"
    resolved = analyzer.resolve_class(className)
    if resolved is None:
        return None, f"未找到班级「{className}」。当前年级下的班级：{'、'.join(classes) or '（暂无）'}"
    return resolved, None


def _build_analysis_tools(analyzer: Union[BucketAnalyzer, GradeScopeAnalyzer], search_fn: Callable):
    """构建 ReAct 工具集（支持按考试/班级选择、跨考试与跨班级对比）"""

    @tool
    def get_class_overview(exam: str = "", className: str = "") -> str:
        """获取指定考试（默认最近一次）的班级整体成绩概览：各科平均分、最高/最低分、及格率、优秀率、总分前5名。参数 exam：考试名称（如期中、期末），可留空；className：班级名称，多班级（全年级）范围下必填，单班级范围可留空"""
        cls, err = _class_err(analyzer, className)
        if err:
            return err
        bucket = analyzer if cls is None else analyzer.class_analyzer(cls)
        if bucket is None:
            return f"未找到班级「{className}」的数据。"
        resolved, err = _resolve_exam(bucket, exam)
        if err:
            return err
        ov = bucket.get_class_overview(exam=resolved)
        if not ov:
            return "暂无成绩数据，请先上传成绩单。"
        exam_label = f"【{resolved or bucket.latest_exam()}】" if bucket.list_exams() else ""
        lines = [f"{exam_label}共 {ov.total_students} 名学生，{len(ov.subjects)} 门科目。", ""]
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
    def get_student_detail(student_name: str, exam: str = "", className: str = "") -> str:
        """获取指定学生在指定考试（默认最近一次）的详细分析：各科成绩、排名、优势/薄弱科目、是否偏科。参数：student_name、exam（考试名称，可留空）、className（班级名称，多班级范围下必填）"""
        cls, err = _class_err(analyzer, className)
        if err:
            return err
        bucket = analyzer if cls is None else analyzer.class_analyzer(cls)
        if bucket is None:
            return f"未找到班级「{className}」的数据。"
        resolved, err = _resolve_exam(bucket, exam)
        if err:
            return err
        r = bucket.get_student_detail(student_name, exam=resolved)
        if not r:
            names = "，".join(bucket.student_names(exam=resolved)[:20])
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
            lines.append("WARNING：该学生存在明显偏科现象")
        return "\n".join(lines)

    @tool
    def get_subject_distribution(subject: str, exam: str = "", className: str = "") -> str:
        """获取指定科目在指定考试（默认最近一次）的分数段分布。参数：subject（科目名称）、exam（考试名称，可留空）、className（班级名称，多班级范围下必填）"""
        cls, err = _class_err(analyzer, className)
        if err:
            return err
        bucket = analyzer if cls is None else analyzer.class_analyzer(cls)
        if bucket is None:
            return f"未找到班级「{className}」的数据。"
        resolved, err = _resolve_exam(bucket, exam)
        if err:
            return err
        d = bucket.get_subject_distribution(subject, exam=resolved)
        if not d:
            return f"未找到科目「{subject}」。当前可用的科目：{'，'.join(bucket.subjects(exam=resolved))}"
        lines = [f"【{d['subject']}】共 {d['count']} 人，平均分={d['average']}", "分数段分布："]
        for seg, count in d["distribution"].items():
            lines.append(f"  {seg}：{count} 人")
        return "\n".join(lines)

    @tool
    def get_top_students(n: int = 5, exam: str = "", className: str = "") -> str:
        """获取指定考试（默认最近一次）总分前 N 名学生。参数：n（默认5）、exam（考试名称，可留空）、className（班级名称，多班级范围下必填）"""
        cls, err = _class_err(analyzer, className)
        if err:
            return err
        bucket = analyzer if cls is None else analyzer.class_analyzer(cls)
        if bucket is None:
            return f"未找到班级「{className}」的数据。"
        resolved, err = _resolve_exam(bucket, exam)
        if err:
            return err
        items = bucket.get_top_students(n, exam=resolved)
        if not items:
            return "暂无成绩数据。"
        lines = [f"总分前 {n} 名："]
        for i, item in enumerate(items, 1):
            lines.append(f"  {i}. {item['name']}：{item['total']}")
        return "\n".join(lines)

    @tool
    def get_pianke_students(exam: str = "", className: str = "") -> str:
        """检测指定考试（默认最近一次）中存在明显偏科的学生（最高分与最低分差距超过30分）。参数：exam（考试名称，可留空）、className（班级名称，多班级范围下必填）"""
        cls, err = _class_err(analyzer, className)
        if err:
            return err
        bucket = analyzer if cls is None else analyzer.class_analyzer(cls)
        if bucket is None:
            return f"未找到班级「{className}」的数据。"
        resolved, err = _resolve_exam(bucket, exam)
        if err:
            return err
        names = bucket.get_pianke_students(exam=resolved)
        if not names:
            return "未检测到明显偏科的学生。"
        return f"共 {len(names)} 名学生可能存在偏科：\n" + "\n".join(f"  - {n}" for n in names)

    @tool
    def get_weakest_subject(exam: str = "", className: str = "") -> str:
        """找出指定考试（默认最近一次）全班平均分最低的科目。参数：exam（考试名称，可留空）、className（班级名称，多班级范围下必填）"""
        cls, err = _class_err(analyzer, className)
        if err:
            return err
        bucket = analyzer if cls is None else analyzer.class_analyzer(cls)
        if bucket is None:
            return f"未找到班级「{className}」的数据。"
        resolved, err = _resolve_exam(bucket, exam)
        if err:
            return err
        subj = bucket.get_weakest_subject(exam=resolved)
        if not subj:
            return "暂无成绩数据。"
        dist = bucket.get_subject_distribution(subj, exam=resolved)
        lines = [f"全班最薄弱科目：{subj}"]
        if dist:
            lines.append(f"  平均分={dist['average']}，共 {dist['count']} 人")
            for seg, count in dist["distribution"].items():
                lines.append(f"  {seg}：{count} 人")
        return "\n".join(lines)

    @tool
    def search_grade_document(query: str) -> str:
        """在当前成绩数据（单班或全年级范围）中搜索相关信息。参数：搜索关键词"""
        result = search_fn(query)
        return result if result else "在文档中未找到匹配的内容。"

    @tool
    def compare_exams(subject: str = "", student_name: str = "", className: str = "") -> str:
        """对比同一班级不同考试（期中/期末/月考等）的成绩：可按科目或学生对比，不传参数时对比班级整体。参数：subject（科目名称）、student_name（学生姓名）、className（班级名称，多班级范围下必填）"""
        cls, err = _class_err(analyzer, className)
        if err:
            return err
        bucket = analyzer if cls is None else analyzer.class_analyzer(cls)
        if bucket is None:
            return f"未找到班级「{className}」的数据。"
        result = bucket.compare_exams(subject=subject, student_name=student_name)
        if not result:
            return "暂无多次考试数据可对比。"
        return result

    @tool
    def compare_classes(classes: str = "", subject: str = "", exam: str = "") -> str:
        """对比同一年级不同班级的成绩（需当前会话为全年级范围）。参数：classes（班级列表，逗号分隔，缺省为全部班级）、subject（科目名称，可选）、exam（考试名称，可选，缺省为各班共有的最近一次考试）"""
        if not hasattr(analyzer, "compare_classes"):
            return "当前会话为单个班级范围，无法跨班对比；请新建「全部班级」范围的会话。"
        result = analyzer.compare_classes(classes=classes, subject=subject, exam=exam)
        if not result:
            return "暂无可对比的班级数据。"
        return result

    @tool
    def get_chart_data(chart_type: str, student_name: str = "", subject: str = "", exam: str = "", className: str = "", n: int = 10) -> str:
        """生成成绩可视化图表数据，返回前端 ECharts 可渲染的 JSON。chart_type 可选：subject_avg(各科平均分柱状图)/student_radar(学生雷达图)/subject_distribution(分数段分布)/top_students(总分排名)/pianke_gap(偏科差距)/class_overview(班级总览)/exam_compare(各次考试对比)/class_compare(各班级对比)。可选参数 student_name、subject、exam（考试名称）、className（班级名称，多班级范围下必填）、n(默认10)"""
        chart_gen = ChartGenerator(analyzer)
        result = chart_gen.generate(
            chart_type,
            student_name=student_name,
            subject=subject,
            exam=exam,
            className=className,
            n=n,
        )
        if result:
            return "::chart::" + result
        return "图表生成失败"

    tools = [
        get_class_overview, get_student_detail, get_subject_distribution,
        get_top_students, get_pianke_students, get_weakest_subject,
        search_grade_document,
        compare_exams,
        get_chart_data,
    ]
    if hasattr(analyzer, "compare_classes"):
        tools.append(compare_classes)
    return tools


class ConsultantService:
    """ReAct 教育分析 Agent —— 对话记忆持久化至 Redis，支持集群部署"""

    def __init__(self):
        self.memory_store = RedisChatMemoryStore()

    def _get_llm(self):
        """获取 LLM 实例"""
        return ChatOpenAI(
            model=settings.openai_model_name,
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            temperature=0.7,
        )

    async def chat(self, memory_id: str, message: str,
                   analyzer: Optional[Union[BucketAnalyzer, GradeScopeAnalyzer]] = None,
                   search_fn: Optional[Callable] = None) -> str:
        """非流式对话：通过 ReAct Agent 一次性返回完整回复"""
        result = []
        async for chunk in self.chat_stream(memory_id, message, analyzer, search_fn):
            result.append(chunk)
        return "".join(result)

    async def chat_stream(self, memory_id: str, message: str,
                           analyzer: Optional[Union[BucketAnalyzer, GradeScopeAnalyzer]] = None,
                           search_fn: Optional[Callable] = None):
        """SSE 流式对话：逐 token 返回 ReAct Agent 的推理过程"""

        tools = []
        if analyzer:
            search = search_fn or (lambda q: None)
            tools = _build_analysis_tools(analyzer, search)

        llm = self._get_llm()
        system = SystemMessage(content=SYSTEM_PROMPT)
        history = self._get_history(memory_id)
        user_msg = HumanMessage(content=message)

        logger.info(
            "[Agent 开始推理] memory_id=%s | 历史轮数=%d | 用户消息=%s",
            memory_id, len(history) // 2, message[:80]
        )

        if tools:
            agent = create_react_agent(llm, tools)
            full = ""

            tool_seq = 0
            tool_timers: dict[str, float] = {}

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
                        # 图表工具：直接把有效图表数据注入回复流，避免依赖模型回显导致前端无法渲染
                        if name == "get_chart_data" and output.startswith("::chart::"):
                            try:
                                chart_obj = json.loads(output[len("::chart::"):])
                                if chart_obj.get("type"):
                                    yield f"\n{output}\n"
                            except Exception:
                                pass

            logger.info(
                "[Agent 推理结束] memory_id=%s | 共调用 %d 个工具 | 回复长度=%d",
                memory_id, tool_seq, len(full)
            )

            response_text = full.strip() or "抱歉，无法处理该请求。"
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
        """读取会话历史：超过阈值时生成滚动摘要，上下文 = 摘要 + 最近 N 条原文"""
        raw = self.memory_store.get_messages(memory_id)
        raw.reverse()
        limit = settings.chat_history_turns
        summary = self.memory_store.get_summary(memory_id)

        if len(raw) > limit:
            overflow = raw[:len(raw) - limit]
            recent = raw[-limit:]
            summary = self._build_rolling_summary(memory_id, summary, overflow)
            if summary:
                self.memory_store.save_summary(memory_id, summary)
            # 已摘要的旧消息从列表移除，保持列表有界
            self.memory_store.trim_messages(memory_id, limit)
            logger.info(
                "[滚动摘要] memory_id=%s | 溢出=%d 条 | 保留最近 %d 条",
                memory_id, len(overflow), limit
            )
        else:
            recent = raw

        messages = []
        if summary:
            messages.append(SystemMessage(content=f"以下是更早对话的摘要：\n{summary}"))
        for item in recent:
            role = item.get("role", "")
            content = item.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
        return messages

    def _build_rolling_summary(self, memory_id: str, existing_summary: Optional[str],
                               overflow_messages: list) -> str:
        """调用 LLM 将已有摘要 + 溢出消息压缩为新的滚动摘要（失败时保留旧摘要）"""
        parts = []
        if existing_summary:
            parts.append(f"已有摘要：\n{existing_summary}")
        transcript = "\n".join(
            f"{'用户' if item.get('role') == 'user' else '助手'}：{item.get('content', '')}"
            for item in overflow_messages
        )
        if transcript:
            parts.append(f"新增对话：\n{transcript}")
        user_prompt = "\n\n".join(parts) if parts else "（暂无历史内容）"
        try:
            llm = self._get_llm()
            response = llm.invoke([
                SystemMessage(content=SUMMARY_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ])
            text = getattr(response, "content", str(response)).strip()
            return text or (existing_summary or "")
        except Exception as e:
            logger.warning("[滚动摘要生成失败] memory_id=%s | %s", memory_id, e)
            return existing_summary or ""

    def _save_history(self, memory_id: str, user_msg: str, assistant_msg: str):
        """保存一轮对话到 Redis"""
        self.memory_store.save_message(memory_id, "user", user_msg)
        self.memory_store.save_message(memory_id, "assistant", assistant_msg)
        total = len(self.memory_store.get_messages(memory_id)) // 2
        logger.info(
            "[对话记忆已保存] memory_id=%s | 累计轮数=%d",
            memory_id, total
        )

    def delete_memory(self, memory_id: str):
        """删除指定会话的 Redis 历史记录"""
        self.memory_store.delete_messages(memory_id)

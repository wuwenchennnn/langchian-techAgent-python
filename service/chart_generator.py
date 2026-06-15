"""成绩图表数据生成器：将 GradeAnalyzer 统计结果转为前端 ECharts 可渲染的 JSON"""

import json
import logging
from typing import Optional

from service.grade_analyzer import GradeAnalyzer

logger = logging.getLogger(__name__)

CHART_TYPES = {
    "subject_avg": "各科平均分对比（柱状图）",
    "student_radar": "学生各科成绩雷达图",
    "subject_distribution": "科目分数段分布（柱状图）",
    "top_students": "总分排名（横向柱状图）",
    "pianke_gap": "偏科学生差距分析（柱状图）",
    "class_overview": "班级成绩总览（多指标图）",
}


class ChartGenerator:
    """根据 GradeAnalyzer 数据生成 ECharts 配置 JSON"""

    def __init__(self, analyzer: GradeAnalyzer):
        self.analyzer = analyzer

    def generate(self, chart_type: str, **kwargs) -> Optional[str]:
        """
        生成图表 JSON 字符串

        Args:
            chart_type: 图表类型（subject_avg / student_radar / subject_distribution / top_students / pianke_gap / class_overview）
            kwargs: 额外参数，如 student_name、subject、n

        Returns:
            JSON 字符串，失败返回 None
        """
        handler = getattr(self, f"_gen_{chart_type}", None)
        if handler is None:
            available = "、".join(CHART_TYPES.keys())
            return json.dumps({"error": f"不支持的图表类型「{chart_type}」，可选：{available}"}, ensure_ascii=False)

        try:
            result = handler(**kwargs)
            if result is None:
                return json.dumps({"error": "数据不足，无法生成图表"}, ensure_ascii=False)
            logger.info("[图表生成] type=%s | title=%s", chart_type, result.get("title", ""))
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            logger.warning("[图表生成失败] type=%s | error=%s", chart_type, e)
            return json.dumps({"error": f"图表生成失败: {e}"}, ensure_ascii=False)

    # ── 各科平均分对比 ──
    def _gen_subject_avg(self) -> Optional[dict]:
        ov = self.analyzer.get_class_overview()
        if not ov or not ov.subject_stats:
            return None
        return {
            "type": "bar",
            "title": "各科平均分对比",
            "xAxis": [ss.subject for ss in ov.subject_stats],
            "series": [{
                "name": "平均分",
                "data": [ss.average for ss in ov.subject_stats],
            }],
            "option": {
                "yAxis": {"name": "分数"},
                "tooltip": {},
            },
        }

    # ── 学生雷达图 ──
    def _gen_student_radar(self, student_name: str = "") -> Optional[dict]:
        if not student_name:
            return None
        r = self.analyzer.get_student_detail(student_name)
        if not r:
            return None

        # 班级各科平均分作为对比
        ov = self.analyzer.get_class_overview()
        avg_map = {}
        if ov:
            avg_map = {ss.subject: ss.average for ss in ov.subject_stats}

        subjects = [s.subject for s in r.subjects]
        scores = [s.score for s in r.subjects]
        avgs = [avg_map.get(s.subject, 0) for s in r.subjects]

        return {
            "type": "radar",
            "title": f"{student_name} 各科成绩雷达图",
            "indicator": [{"name": subj, "max": 100} for subj in subjects],
            "series": [
                {"name": student_name, "data": scores},
                {"name": "班级平均", "data": avgs},
            ],
            "option": {
                "radar": {"shape": "polygon"},
                "tooltip": {},
            },
        }

    # ── 科目分数段分布 ──
    def _gen_subject_distribution(self, subject: str = "") -> Optional[dict]:
        if not subject:
            return None
        d = self.analyzer.get_subject_distribution(subject)
        if not d:
            return None
        dist = d.get("distribution", {})
        segments = list(dist.keys())
        counts = list(dist.values())
        return {
            "type": "bar",
            "title": f"{subject} 分数段分布",
            "xAxis": segments,
            "series": [{
                "name": "人数",
                "data": counts,
            }],
            "option": {
                "yAxis": {"name": "人数"},
                "tooltip": {},
                "color": ["#5470c6"],
            },
        }

    # ── 总分排名 ──
    def _gen_top_students(self, n: int = 10) -> Optional[dict]:
        items = self.analyzer.get_top_students(n)
        if not items:
            return None
        names = [item["name"] for item in items]
        totals = [item["total"] for item in items]
        return {
            "type": "bar",
            "title": f"总分前 {len(items)} 名",
            "xAxis": names,
            "series": [{
                "name": "总分",
                "data": totals,
            }],
            "option": {
                "yAxis": {"name": "总分"},
                "tooltip": {},
                "xAxis_rotate": 30 if len(names) > 5 else 0,
            },
        }

    # ── 偏科差距 ──
    def _gen_pianke_gap(self) -> Optional[dict]:
        names = self.analyzer.get_pianke_students()
        if not names:
            return None

        gaps = []
        for name in names:
            r = self.analyzer.get_student_detail(name)
            if r and r.subjects:
                scores = [s.score for s in r.subjects]
                gap = max(scores) - min(scores)
                gaps.append({"name": name, "gap": round(gap, 1)})

        if not gaps:
            return None

        gaps.sort(key=lambda x: x["gap"], reverse=True)
        return {
            "type": "bar",
            "title": "偏科学生科目差距",
            "xAxis": [g["name"] for g in gaps],
            "series": [{
                "name": "最大分差",
                "data": [g["gap"] for g in gaps],
            }],
            "option": {
                "yAxis": {"name": "分差"},
                "tooltip": {},
                "color": ["#ee6666"],
            },
        }

    # ── 班级总览 ──
    def _gen_class_overview(self) -> Optional[dict]:
        ov = self.analyzer.get_class_overview()
        if not ov or not ov.subject_stats:
            return None
        return {
            "type": "bar",
            "title": "班级各科成绩总览",
            "xAxis": [ss.subject for ss in ov.subject_stats],
            "series": [
                {"name": "平均分", "data": [ss.average for ss in ov.subject_stats]},
                {"name": "最高分", "data": [ss.max_score for ss in ov.subject_stats]},
                {"name": "最低分", "data": [ss.min_score for ss in ov.subject_stats]},
            ],
            "option": {
                "yAxis": {"name": "分数"},
                "tooltip": {},
                "legend": {},
            },
        }

    @staticmethod
    def list_types() -> str:
        """返回所有可用图表类型及说明"""
        lines = ["可用图表类型："]
        for key, desc in CHART_TYPES.items():
            lines.append(f"  - {key}: {desc}")
        return "\n".join(lines)
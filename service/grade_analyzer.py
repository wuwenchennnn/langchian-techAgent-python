"""智能成绩分析引擎：自动识别列结构 + 统计分析 + ReAct 工具"""

import math
import re
from collections import defaultdict
from typing import Optional

from schemas.analysis import (
    StudentScore, StudentReport, SubjectStats,
    ClassOverview, AnalysisResult,
)

# 科目关键词库（用于列识别）
SUBJECT_KEYWORDS = [
    "语文", "数学", "英语", "物理", "化学", "生物",
    "政治", "历史", "地理", "总分", "总成绩", "平均分",
    "文综", "理综", "技术", "信息", "体育", "音乐", "美术",
]

# 学生标识关键词
STUDENT_KEYWORDS = ["姓名", "学生", "名字", "名称"]

# 学号关键词
ID_KEYWORDS = ["学号", "编号", "考号", "准考证号"]

# 班级关键词
CLASS_KEYWORDS = ["班级", "班"]

# 成绩关键词（用于排除非分数列）
SCORE_KEYWORDS = ["成绩", "分数", "得分", "成绩单"]


class GradeAnalyzer:
    """智能成绩分析器"""

    def __init__(self):
        self._parsed_data: list[StudentScore] = []
        self._student_names: list[str] = []
        self._subjects: list[str] = []

    # ───── 智能列识别 ─────
    def parse(self, raw_text: str) -> list[StudentScore]:
        """主入口：从 Excel 提取的文本中解析成绩数据"""
        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
        if not lines:
            return []

        # 步骤1：找表头行
        header_idx = self._find_header_row(lines)
        if header_idx == -1:
            header_idx = 0
        header_line = lines[header_idx]

        # 步骤2：解析列名
        columns = self._split_cells(header_line)

        # 步骤3：分类列
        col_types = self._classify_columns(columns)

        # 步骤4：判断布局类型
        layout = self._detect_layout(col_types)

        # 步骤5：按布局解析数据行
        data_lines = lines[header_idx + 1:]
        if layout == "long":
            records = self._parse_long_format(data_lines, col_types, columns)
        else:
            records = self._parse_wide_format(data_lines, col_types, columns)

        self._parsed_data = records
        self._student_names = sorted(set(r.student_name for r in records))
        self._subjects = sorted(set(r.subject for r in records if r.subject not in ("总分", "总成绩", "平均分")))

        return records

    def _find_header_row(self, lines: list[str]) -> int:
        """扫描前15行，找最可能的表头行"""
        best_idx, best_score = 0, 0
        for i, line in enumerate(lines[:15]):
            cells = self._split_cells(line)
            score = 0
            for cell in cells:
                low = cell.lower().replace(" ", "")
                if any(kw in low for kw in STUDENT_KEYWORDS):
                    score += 5
                if any(kw in low for kw in SUBJECT_KEYWORDS):
                    score += 3
                if any(kw in low for kw in ID_KEYWORDS):
                    score += 4
                if any(kw in low for kw in CLASS_KEYWORDS):
                    score += 2
            if score > best_score:
                best_score = score
                best_idx = i
        return best_idx if best_score >= 3 else 0

    def _split_cells(self, line: str) -> list[str]:
        """按制表符或连续空格切分单元格"""
        if "\t" in line:
            return [c.strip() for c in line.split("\t")]
        # 连续2个以上空格分隔
        return re.split(r"\s{2,}", line.strip())

    def _classify_columns(self, columns: list[str]) -> list[str]:
        """将每列分为：student_name / student_id / class / subject_xxx / score / ignore"""
        types = []
        for col in columns:
            low = col.replace(" ", "")
            if any(kw in low for kw in STUDENT_KEYWORDS):
                types.append("student_name")
            elif any(kw in low for kw in ID_KEYWORDS):
                types.append("student_id")
            elif any(kw in low for kw in CLASS_KEYWORDS):
                types.append("class")
            elif any(kw in low for kw in SUBJECT_KEYWORDS):
                # 标记具体科目
                matched = [kw for kw in SUBJECT_KEYWORDS if kw in low]
                types.append(f"subject_{matched[0]}" if matched else "subject")
            else:
                types.append("unknown")
        return types

    def _detect_layout(self, col_types: list[str]) -> str:
        """判断宽表还是长表
        宽表：有多列 subject_xxx 类型
        长表：有一列 subject 类型 + 一列 score
        """
        subject_cols = sum(1 for t in col_types if t.startswith("subject_"))
        has_name = "student_name" in col_types
        if subject_cols >= 2 and has_name:
            return "wide"
        return "long"

    # ───── 宽表解析（一行一个学生，列是各科成绩）─────
    def _parse_wide_format(self, data_lines, col_types, columns) -> list[StudentScore]:
        """宽表：姓名 | 语文 | 数学 | 英语 | ..."""
        records = []
        name_idx = self._find_index(col_types, "student_name")
        if name_idx == -1:
            name_idx = 0  # fallback：第一列当作姓名

        subject_indices = [
            (i, t.split("_", 1)[1]) for i, t in enumerate(col_types)
            if t.startswith("subject_")
        ]

        for line in data_lines:
            cells = self._split_cells(line)
            if len(cells) < len(columns):
                continue
            student_name = cells[name_idx].strip() if name_idx < len(cells) else ""
            if not student_name or self._looks_like_header(student_name):
                continue
            for si, subj in subject_indices:
                if si >= len(cells):
                    continue
                score = self._parse_score(cells[si])
                if score is not None:
                    records.append(StudentScore(
                        student_name=student_name,
                        subject=subj,
                        score=score,
                    ))
        return records

    # ───── 长表解析（一行一条记录）─────
    def _parse_long_format(self, data_lines, col_types, columns) -> list[StudentScore]:
        """长表：姓名 | 科目 | 分数"""
        records = []
        name_idx = self._find_index(col_types, "student_name")
        if name_idx == -1:
            name_idx = 0

        subject_indices = [i for i, t in enumerate(col_types) if t.startswith("subject_") or t == "subject"]
        if not subject_indices:
            subject_indices = [1]  # fallback：第二列
        subject_idx = subject_indices[0]

        # 找分数列（unknown 类型且看起来像数字列名，或者是明确的成绩列）
        score_idx = self._find_score_column(col_types, data_lines[:5], columns)

        for line in data_lines:
            cells = self._split_cells(line)
            if len(cells) < max(name_idx, subject_idx, score_idx) + 1:
                continue
            student_name = cells[name_idx].strip() if name_idx < len(cells) else ""
            subject = cells[subject_idx].strip() if subject_idx < len(cells) else ""
            if not student_name or self._looks_like_header(student_name):
                continue

            score = self._parse_score(cells[score_idx]) if score_idx < len(cells) else None
            if score is not None:
                records.append(StudentScore(
                    student_name=student_name,
                    subject=subject,
                    score=score,
                ))
        return records

    def _find_score_column(self, col_types, sample_lines, columns) -> int:
        """在长表格式中找出分数列"""
        for i, t in enumerate(col_types):
            low = columns[i].replace(" ", "") if i < len(columns) else ""
            if any(kw in low for kw in SCORE_KEYWORDS):
                return i
        # fallback：找 unknown 列中数值比例最高的
        best_idx, best_ratio = 2, 0
        for i, t in enumerate(col_types):
            if t == "unknown":
                scores = [self._parse_score(self._split_cells(l)[i])
                          for l in sample_lines if i < len(self._split_cells(l))]
                ratio = sum(1 for s in scores if s is not None) / max(len(scores), 1)
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_idx = i
        return best_idx

    # ───── 统计分析 ─────
    def get_class_overview(self) -> Optional[ClassOverview]:
        """班级整体概览"""
        if not self._parsed_data:
            return None

        students = self._student_names
        subjects = self._subjects
        if not subjects or not students:
            return None

        # 按科目聚合
        by_subject: dict[str, list[float]] = defaultdict(list)
        for r in self._parsed_data:
            if r.subject in subjects:
                by_subject[r.subject].append(r.score)

        subject_stats = []
        for subj in subjects:
            scores = by_subject.get(subj, [])
            if not scores:
                continue
            sorted_scores = sorted(scores)
            n = len(sorted_scores)
            stats = SubjectStats(
                subject=subj,
                average=round(sum(scores) / n, 1),
                max_score=round(max(scores), 1),
                min_score=round(min(scores), 1),
                median=round(sorted_scores[n // 2], 1),
                pass_rate=round(sum(1 for s in scores if s >= 60) / n * 100, 1),
                excellent_rate=round(sum(1 for s in scores if s >= 85) / n * 100, 1),
                distribution=self._calc_distribution(scores),
            )
            subject_stats.append(stats)

        # 总分排名
        total_scores = self._calc_total_scores()
        sorted_totals = sorted(total_scores.values(), reverse=True)
        class_avg_total = round(sum(sorted_totals) / len(sorted_totals), 1) if sorted_totals else 0

        top_students = [
            {"name": name, "total": total_scores[name]}
            for name in sorted(total_scores, key=total_scores.get, reverse=True)[:5]
        ]

        return ClassOverview(
            total_students=len(students),
            subjects=subjects,
            subject_stats=subject_stats,
            class_average_total=class_avg_total,
            top_students=top_students,
        )

    def get_student_detail(self, student_name: str) -> Optional[StudentReport]:
        """单个学生详细分析"""
        records = [r for r in self._parsed_data if r.student_name == student_name]
        if not records:
            return None

        total = sum(r.score for r in records)
        avg = round(total / len(records), 1)

        # 排名
        total_scores = self._calc_total_scores()
        sorted_names = sorted(total_scores, key=total_scores.get, reverse=True)
        rank = sorted_names.index(student_name) + 1 if student_name in sorted_names else -1

        # 强弱科判定（低于均分 → 弱，高于均分 → 强）
        by_subject = defaultdict(list)
        for r in self._parsed_data:
            by_subject[r.subject].append(r.score)

        subject_stats = {}
        for subj, scores in by_subject.items():
            avg_s = sum(scores) / len(scores)
            subject_stats[subj] = avg_s

        weak = [
            r.subject for r in records
            if r.subject in subject_stats and r.score < subject_stats[r.subject]
        ]
        strong = [
            r.subject for r in records
            if r.subject in subject_stats and r.score >= subject_stats[r.subject]
        ]

        # 偏科检测
        is_pianke = (
            records and
            max(r.score for r in records) - min(r.score for r in records) > 30
        )

        return StudentReport(
            student_name=student_name,
            total_score=round(total, 1),
            average_score=avg,
            rank=rank,
            total_students=len(self._student_names),
            subjects=records,
            weak_subjects=weak,
            strong_subjects=strong,
            is_pianke=is_pianke,
        )

    def get_subject_distribution(self, subject: str) -> Optional[dict]:
        """单科分数段分布"""
        scores = [r.score for r in self._parsed_data if r.subject == subject]
        if not scores:
            return None
        return {
            "subject": subject,
            "count": len(scores),
            "average": round(sum(scores) / len(scores), 1),
            "distribution": self._calc_distribution(scores),
        }

    def get_top_students(self, n: int = 5) -> list[dict]:
        """总分前 N 名"""
        total_scores = self._calc_total_scores()
        sorted_items = sorted(total_scores.items(), key=lambda x: x[1], reverse=True)
        return [{"name": name, "total": score} for name, score in sorted_items[:n]]

    def get_weakest_subject(self) -> Optional[str]:
        """全班最弱科目（均分最低）"""
        if not self._subjects:
            return None
        by_subject = defaultdict(list)
        for r in self._parsed_data:
            by_subject[r.subject].append(r.score)
        avgs = {s: sum(v) / len(v) for s, v in by_subject.items() if v}
        return min(avgs, key=avgs.get) if avgs else None

    def get_pianke_students(self) -> list[str]:
        """偏科学生名单"""
        result = []
        for name in self._student_names:
            report = self.get_student_detail(name)
            if report and report.is_pianke:
                result.append(name)
        return result

    # ───── 辅助方法 ─────
    def _calc_total_scores(self) -> dict[str, float]:
        """计算每个学生的总分"""
        totals = defaultdict(float)
        for r in self._parsed_data:
            if r.subject not in ("总分", "总成绩", "平均分"):
                totals[r.student_name] += r.score
        return dict(totals)

    def _calc_distribution(self, scores: list[float]) -> dict[str, int]:
        """将分数按 0-59/60-69/70-79/80-89/90-100 分段（150分制等比放大）"""
        dist = {"0-59": 0, "60-69": 0, "70-79": 0, "80-89": 0, "90-100": 0}
        for s in scores:
            # 自适应满分：取 max(100, 实际最高分)
            full = max(100, max(scores))
            normalized = s / full * 100
            if normalized < 60:
                dist["0-59"] += 1
            elif normalized < 70:
                dist["60-69"] += 1
            elif normalized < 80:
                dist["70-79"] += 1
            elif normalized < 90:
                dist["80-89"] += 1
            else:
                dist["90-100"] += 1
        return dist

    @staticmethod
    def _parse_score(val: str) -> Optional[float]:
        """尝试解析分数"""
        if not val:
            return None
        val = val.strip().replace(",", "").replace("分", "")
        try:
            s = float(val)
            if 0 <= s <= 200:
                return s
        except (ValueError, TypeError):
            pass
        return None

    @staticmethod
    def _find_index(types: list[str], target: str) -> int:
        for i, t in enumerate(types):
            if t == target or t.startswith(target):
                return i
        return -1

    @staticmethod
    def _looks_like_header(text: str) -> bool:
        """判断文本是否像表头"""
        low = text.lower().replace(" ", "")
        keywords = STUDENT_KEYWORDS + ID_KEYWORDS + CLASS_KEYWORDS + ["科目", "成绩"]
        return any(kw in low for kw in keywords)
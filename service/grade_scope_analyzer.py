"""年级级分析器：聚合同一年级多个班级，支持跨班级成绩对比"""

from typing import Optional

from service.bucket_analyzer import BucketAnalyzer


class GradeScopeAnalyzer:
    """一个年级内多个班级（BucketAnalyzer）的聚合分析器，用于跨班对比"""

    def __init__(self, grade: str, buckets: dict[str, BucketAnalyzer] = None):
        self.grade = grade
        self._buckets: dict[str, BucketAnalyzer] = buckets or {}

    # ---------- 班级与考试 ----------
    def list_classes(self) -> list[str]:
        return list(self._buckets.keys())

    def resolve_class(self, className: str) -> Optional[str]:
        """将用户输入（可能不完整）解析为实际班级名；空值且仅一个班级时自动命中"""
        className = (className or "").strip()
        if not className:
            classes = self.list_classes()
            return classes[0] if len(classes) == 1 else None
        if className in self._buckets:
            return className
        for name in self.list_classes():
            if className in name or name in className:
                return name
        return None

    def class_analyzer(self, className: str) -> Optional[BucketAnalyzer]:
        return self._buckets.get(className)

    def common_exams(self) -> list[str]:
        """至少两个班级都有的考试名称（按首个班级的上传顺序）"""
        counts: dict[str, int] = {}
        order: list[str] = []
        for bucket in self._buckets.values():
            for exam in bucket.list_exams():
                if exam not in counts:
                    counts[exam] = 0
                    order.append(exam)
                counts[exam] += 1
        return [exam for exam in order if counts[exam] >= 2]

    def latest_common_exam(self) -> Optional[str]:
        """共同考试中「作为最多班级最近一次考试」者，平局按名称字典序"""
        common = self.common_exams()
        if not common:
            return None
        best, best_count = None, -1
        for exam in sorted(common):
            count = sum(
                1 for bucket in self._buckets.values()
                if bucket.latest_exam() == exam
            )
            if count > best_count:
                best, best_count = exam, count
        return best

    def _select_classes(self, classes: str) -> list[str]:
        """按逗号分隔的班级列表筛选（缺省全部班级），保持班级原始顺序"""
        names = [c.strip() for c in (classes or "").split(",") if c.strip()]
        if not names:
            return self.list_classes()
        selected = []
        for n in names:
            resolved = self.resolve_class(n)
            if resolved and resolved not in selected:
                selected.append(resolved)
        return selected

    def _resolve_exam_for_classes(self, class_names: list[str], exam: str) -> Optional[str]:
        """指定考试时返回任一班级可解析到的名称；缺省返回共同考试中的最近一次"""
        exam = (exam or "").strip()
        if exam:
            for c in class_names:
                bucket = self._buckets[c]
                found = bucket.resolve_exam(exam)
                if found:
                    return found
            return None
        return self.latest_common_exam()

    # ---------- 单班能力委托（年级级作用域下 className 必填） ----------
    def _bucket_for(self, className: str) -> Optional[BucketAnalyzer]:
        resolved = self.resolve_class(className)
        return self._buckets.get(resolved) if resolved else None

    def get_class_overview(self, className: str, exam: Optional[str] = None):
        bucket = self._bucket_for(className)
        return bucket.get_class_overview(exam=exam) if bucket else None

    def get_student_detail(self, student_name: str, className: str, exam: Optional[str] = None):
        bucket = self._bucket_for(className)
        return bucket.get_student_detail(student_name, exam=exam) if bucket else None

    def get_subject_distribution(self, subject: str, className: str, exam: Optional[str] = None):
        bucket = self._bucket_for(className)
        return bucket.get_subject_distribution(subject, exam=exam) if bucket else None

    def get_top_students(self, n: int = 5, className: str = "", exam: Optional[str] = None):
        bucket = self._bucket_for(className)
        return bucket.get_top_students(n, exam=exam) if bucket else None

    def get_pianke_students(self, className: str = "", exam: Optional[str] = None):
        bucket = self._bucket_for(className)
        return bucket.get_pianke_students(exam=exam) if bucket else None

    def get_weakest_subject(self, className: str = "", exam: Optional[str] = None):
        bucket = self._bucket_for(className)
        return bucket.get_weakest_subject(exam=exam) if bucket else None

    def compare_exams(self, className: str = "", subject: str = "", student_name: str = ""):
        bucket = self._bucket_for(className)
        return bucket.compare_exams(subject=subject, student_name=student_name) if bucket else None

    # ---------- 跨班级对比 ----------
    def compare_classes(self, classes: str = "", subject: str = "", exam: str = "") -> str:
        """跨班级对比：指定班级（逗号分隔，缺省全部）、科目（可选）、考试（可选）"""
        selected = self._select_classes(classes)
        if len(selected) < 2:
            tip = f" 当前年级可选班级：{'、'.join(selected)}" if selected else ""
            return f"至少需要两个班级才能进行跨班对比。{tip}"

        exam_name = self._resolve_exam_for_classes(selected, exam)
        if exam_name is None:
            return f"所选班级中没有考试「{exam}」。各班可用考试：\n" + self._exams_summary(selected)

        # 过滤出实际拥有该考试的班级
        available = []
        for c in selected:
            bucket = self._buckets[c]
            grade_analyzer = bucket.get_exam_analyzer(exam_name)
            if grade_analyzer is not None:
                available.append((c, grade_analyzer))
        if len(available) < 2:
            return (
                f"考试「{exam_name}」至少需要两个班级有数据才能对比。\n"
                + self._exams_summary(selected)
            )

        if subject:
            return self._compare_subject(available, subject, exam_name)
        return self._compare_overview(available, exam_name)

    def _exams_summary(self, class_names: list[str]) -> str:
        lines = []
        for c in class_names:
            bucket = self._buckets[c]
            exams = "、".join(bucket.list_exams()) or "（暂无）"
            lines.append(f"  {c}：{exams}")
        return "\n".join(lines)

    @staticmethod
    def _subject_stats_text(grade_analyzer, subject: str) -> str:
        dist = grade_analyzer.get_subject_distribution(subject)
        if not dist:
            return "无该科目数据"
        segments = "、".join(
            f"{seg}:{count}人" for seg, count in dist["distribution"].items() if count
        )
        return (
            f"平均 {dist['average']}，共 {dist['count']} 人"
            f"（分布：{segments or '无'})"
        )

    def _compare_subject(self, available, subject: str, exam_name: str) -> str:
        lines = [f"【{self.grade}】「{exam_name}」{subject} 各班对比：", ""]
        scored = []
        for c, grade_analyzer in available:
            dist = grade_analyzer.get_subject_distribution(subject)
            if not dist:
                lines.append(f"  {c}：无该科目数据")
                continue
            scored.append((dist["average"], c, dist))
            ov = grade_analyzer.get_class_overview()
            extra = ""
            if ov:
                for ss in ov.subject_stats:
                    if ss.subject == subject:
                        extra = (
                            f"，最高 {ss.max_score}，最低 {ss.min_score}，"
                            f"及格率 {ss.pass_rate}%，优秀率 {ss.excellent_rate}%"
                        )
            lines.append(
                f"  {c}：平均 {dist['average']}{extra}（分布："
                + "、".join(f"{seg}:{count}人" for seg, count in dist["distribution"].items() if count)
                + "）"
            )
        scored.sort(key=lambda x: x[0], reverse=True)
        lines.append("")
        lines.append(f"{subject} 平均分排名：" + "；".join(f"{i}. {c} {avg}" for i, (avg, c, _) in enumerate(scored, 1)))
        return "\n".join(lines)

    def _compare_overview(self, available, exam_name: str) -> str:
        rows = []
        for c, grade_analyzer in available:
            ov = grade_analyzer.get_class_overview()
            if ov:
                rows.append((c, ov))
        if len(rows) < 2:
            return f"考试「{exam_name}」至少需要两个班级有完整数据才能对比。"

        lines = [f"【{self.grade}】各班级「{exam_name}」成绩对比（{len(rows)} 个班）：", ""]

        # 班级总分均分排名
        sorted_rows = sorted(rows, key=lambda x: x[1].class_average_total, reverse=True)
        lines.append("班级总分均分排名：")
        for i, (c, ov) in enumerate(sorted_rows, 1):
            lines.append(f"  {i}. {c}：{ov.class_average_total}")
        lines.append("")

        # 各科平均分对比
        subjects = []
        for _, ov in rows:
            for ss in ov.subject_stats:
                if ss.subject not in subjects:
                    subjects.append(ss.subject)
        lines.append("各科平均分：")
        for subj in subjects:
            parts = []
            for c, ov in rows:
                avg = next((ss.average for ss in ov.subject_stats if ss.subject == subj), None)
                if avg is not None:
                    parts.append(f"{c}={avg}")
            if parts:
                lines.append(f"  {subj}：" + "，".join(parts))

        # 及格率 / 优秀率汇总
        lines.append("")
        for metric_name, attr in (("及格率", "pass_rate"), ("优秀率", "excellent_rate")):
            parts = []
            for c, ov in rows:
                values = [getattr(ss, attr) for ss in ov.subject_stats]
                if values:
                    parts.append(f"{c}={round(sum(values) / len(values), 1)}%")
            if parts:
                lines.append(f"平均{metric_name}：" + "，".join(parts))

        return "\n".join(lines)

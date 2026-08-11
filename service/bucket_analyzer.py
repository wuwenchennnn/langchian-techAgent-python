"""桶分析器：按（年级 + 班级）聚合多份考试成绩，支持按考试选择与跨考试对比"""

from typing import Optional

from service.grade_analyzer import GradeAnalyzer


class BucketAnalyzer:
    """一个（年级 + 班级）桶内多份考试（期中/期末/月考…）的分析器集合"""

    def __init__(
        self,
        grade: str,
        class_name: str,
        analyzers: dict[str, GradeAnalyzer] = None,
        exam_order: list[str] = None,
    ):
        self.grade = grade
        self.class_name = class_name
        self._analyzers: dict[str, GradeAnalyzer] = analyzers or {}
        # 考试顺序按上传先后排列，最后一个为最近上传
        self._exam_order: list[str] = exam_order or [
            name for name in self._analyzers.keys()
        ]

    def add_exam(self, exam_name: str, analyzer: GradeAnalyzer):
        if exam_name not in self._analyzers:
            self._exam_order.append(exam_name)
        self._analyzers[exam_name] = analyzer

    def list_exams(self) -> list[str]:
        """按上传顺序返回考试名称列表"""
        return list(self._exam_order)

    def get_exam_analyzer(self, exam_name: str) -> Optional[GradeAnalyzer]:
        return self._analyzers.get(exam_name)

    def latest_exam(self) -> Optional[str]:
        """最近一次上传的考试名称"""
        return self._exam_order[-1] if self._exam_order else None

    def resolve_exam(self, exam: str) -> Optional[str]:
        """将用户输入（可能不完整）解析为桶内实际考试名称；为空返回 None"""
        exam = (exam or "").strip()
        if not exam:
            return None
        if exam in self._analyzers:
            return exam
        for name in self._exam_order:
            if exam in name or name in exam:
                return name
        return None

    def exam_analyzer(self, exam: Optional[str] = None) -> Optional[GradeAnalyzer]:
        """获取指定考试（缺省最近一次）的分析器"""
        if not self._analyzers:
            return None
        if exam:
            return self._analyzers.get(exam)
        latest = self.latest_exam()
        return self._analyzers.get(latest) if latest else None

    def student_names(self, exam: Optional[str] = None) -> list[str]:
        analyzer = self.exam_analyzer(exam)
        return analyzer._student_names if analyzer else []

    def subjects(self, exam: Optional[str] = None) -> list[str]:
        analyzer = self.exam_analyzer(exam)
        return analyzer._subjects if analyzer else []

    # ---------- 单考试委托（exam 缺省 = 最近一次） ----------
    def get_class_overview(self, exam: Optional[str] = None):
        analyzer = self.exam_analyzer(exam)
        return analyzer.get_class_overview() if analyzer else None

    def get_student_detail(self, student_name: str, exam: Optional[str] = None):
        analyzer = self.exam_analyzer(exam)
        return analyzer.get_student_detail(student_name) if analyzer else None

    def get_subject_distribution(self, subject: str, exam: Optional[str] = None):
        analyzer = self.exam_analyzer(exam)
        return analyzer.get_subject_distribution(subject) if analyzer else None

    def get_top_students(self, n: int = 5, exam: Optional[str] = None):
        analyzer = self.exam_analyzer(exam)
        return analyzer.get_top_students(n) if analyzer else None

    def get_pianke_students(self, exam: Optional[str] = None):
        analyzer = self.exam_analyzer(exam)
        return analyzer.get_pianke_students() if analyzer else None

    def get_weakest_subject(self, exam: Optional[str] = None):
        analyzer = self.exam_analyzer(exam)
        return analyzer.get_weakest_subject() if analyzer else None

    # ---------- 跨考试对比 ----------
    def compare_exams(self, subject: str = "", student_name: str = "") -> Optional[str]:
        """按科目 / 学生 / 班级整体对比各次考试"""
        exams = self.list_exams()
        if not exams:
            return None

        if subject:
            lines = [f"科目【{subject}】各次考试对比："]
            for exam in exams:
                analyzer = self._analyzers[exam]
                dist = analyzer.get_subject_distribution(subject)
                if dist:
                    lines.append(
                        f"  {exam}：平均分 {dist['average']}，共 {dist['count']} 人"
                    )
                else:
                    lines.append(f"  {exam}：无该科目数据")
            return "\n".join(lines)

        if student_name:
            lines = [f"学生【{student_name}】各次考试对比："]
            for exam in exams:
                analyzer = self._analyzers[exam]
                report = analyzer.get_student_detail(student_name)
                if report:
                    score_text = "，".join(
                        f"{s.subject}={s.score}" for s in report.subjects
                    )
                    lines.append(
                        f"  {exam}：总分 {report.total_score}，平均分 {report.average_score}"
                        f"（{score_text}）"
                    )
                else:
                    lines.append(f"  {exam}：无该学生数据")
            return "\n".join(lines)

        lines = ["各次考试班级整体对比："]
        for exam in exams:
            analyzer = self._analyzers[exam]
            overview = analyzer.get_class_overview()
            if overview:
                subject_avgs = "，".join(
                    f"{ss.subject}={ss.average}" for ss in overview.subject_stats
                )
                lines.append(
                    f"  {exam}：共 {overview.total_students} 人，"
                    f"班级总分均分 {overview.class_average_total}（{subject_avgs}）"
                )
            else:
                lines.append(f"  {exam}：暂无可对比数据")
        return "\n".join(lines)

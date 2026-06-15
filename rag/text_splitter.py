from typing import List, Optional

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


class GradeTextSplitter:
    """成绩单专用语义切块器：以学生记录 / 科目 / 班级概览为粒度生成 chunk"""

    def split_by_records(
        self,
        records: list,
        student_names: list[str],
        subjects: list[str],
    ) -> List[str]:
        """
        从已解析的结构化成绩数据中生成语义完整的 chunk:
        - 每个学生一条 chunk（含所有科目成绩）
        - 每个科目一条 chunk（含所有学生成绩）
        - 一条班级总览 chunk
        """
        chunks = []

        # — 按学生分组 —
        by_student: dict[str, list] = {}
        for r in records:
            by_student.setdefault(r.student_name, []).append(r)

        for name in student_names:
            scores = by_student.get(name, [])
            if not scores:
                continue
            subject_lines = []
            total = 0.0
            for s in scores:
                subject_lines.append(f"{s.subject}: {s.score}")
                total += s.score
            avg = round(total / len(scores), 1)
            subject_detail = "，".join(subject_lines)
            chunk = (
                f"学生 {name}，各科成绩：{subject_detail}。"
                f"总分 {total}，平均分 {avg}"
            )
            chunks.append(chunk)

        # — 按科目分组 —
        by_subject: dict[str, list] = {}
        for r in records:
            by_subject.setdefault(r.subject, []).append(r)

        for subj in subjects:
            scores_list = by_subject.get(subj, [])
            if not scores_list:
                continue
            values = [s.score for s in scores_list]
            avg_score = round(sum(values) / len(values), 1)
            max_score = max(values)
            min_score = min(values)
            score_list = "，".join(f"{s.student_name}={s.score}" for s in scores_list)
            chunk = (
                f"科目 {subj}：共{len(values)}人，"
                f"平均分 {avg_score}，最高分 {max_score}，最低分 {min_score}。"
                f"分数：{score_list}"
            )
            chunks.append(chunk)

        # — 班级总览 —
        total_students = len(student_names)
        total_subjects = len(subjects)
        all_scores = [r.score for r in records]
        overall_avg = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0
        overview_chunk = (
            f"全班共{total_students}名学生，{total_subjects}门科目："
            f"{'、'.join(subjects)}。"
            f"全班总平均分 {overall_avg}。"
            f"学生名单：{'、'.join(student_names)}"
        )
        chunks.append(overview_chunk)

        return chunks
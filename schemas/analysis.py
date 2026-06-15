"""成绩分析相关数据模型"""

from typing import Optional
from pydantic import BaseModel


class StudentScore(BaseModel):
    """单条成绩记录"""
    student_name: str
    subject: str
    score: float


class StudentReport(BaseModel):
    """单个学生的分析报告"""
    student_name: str
    total_score: float
    average_score: float
    rank: int
    total_students: int
    subjects: list[StudentScore]
    weak_subjects: list[str]   # 弱势科目
    strong_subjects: list[str]  # 优势科目
    is_pianke: bool = False     # 是否偏科


class SubjectStats(BaseModel):
    """单科统计"""
    subject: str
    average: float
    max_score: float
    min_score: float
    median: float
    pass_rate: float          # 及格率（>=60）
    excellent_rate: float     # 优秀率（>=85）
    distribution: dict[str, int]  # 分数段分布


class ClassOverview(BaseModel):
    """班级整体概览"""
    total_students: int
    subjects: list[str]
    subject_stats: list[SubjectStats]
    class_average_total: float
    top_students: list[dict]  # [{name, total}]


class AnalysisResult(BaseModel):
    """完整分析结果"""
    overview: Optional[ClassOverview] = None
    students: list[StudentReport] = []
    summary_text: str = ""   # 可注入 prompt 的中文摘要
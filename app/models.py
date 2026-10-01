"""Data shapes shared by the API, the agents, and the store."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class RubricItem(BaseModel):
    points: float
    description: str
    # Alternatives a mock grader looks for; Gemini ignores these and reads the description.
    keywords: list[str] = Field(default_factory=list)


class Question(BaseModel):
    id: str
    title: str
    max_points: float
    page: int
    # Normalized [x0, y0, x1, y1], fractions of page width and height.
    region: tuple[float, float, float, float]
    prompt: str = ""
    answer: str = ""
    rubric: list[RubricItem] = Field(default_factory=list)


class ExamConfig(BaseModel):
    exam_id: str
    title: str
    course: str = ""
    pages: int = 1
    confidence_threshold: float = 0.8
    spot_check_rate: float = 0.1
    questions: list[Question]

    def question(self, qid: str) -> Question:
        for q in self.questions:
            if q.id == qid:
                return q
        raise KeyError(qid)


class Status(str, Enum):
    received = "received"
    cropped = "cropped"
    transcribed = "transcribed"
    graded = "graded"
    needs_review = "needs_review"
    approved = "approved"
    failed = "failed"


class CriterionScore(BaseModel):
    description: str
    awarded: float
    max_points: float
    rationale: str = ""


class QuestionResult(BaseModel):
    question_id: str
    # Agent 1
    crop_path: str = ""
    pii_redacted: bool = False
    # Agent 2
    transcript: str = ""
    ocr_confidence: float = 0.0
    # Agent 3
    criteria: list[CriterionScore] = Field(default_factory=list)
    score: float = 0.0
    max_points: float = 0.0
    feedback: str = ""
    grader_confidence: float = 0.0
    injection_blocked: bool = False
    # Agent 4
    confidence: float = 0.0
    route: str = ""  # "auto_approve" | "review" | "spot_check"
    route_reason: str = ""
    # Instructor review
    final_score: float | None = None
    instructor_comment: str = ""
    reviewed: bool = False


class Submission(BaseModel):
    id: str
    exam_id: str
    # The student's identity lives only here, set by the instructor at upload.
    # Agents receive the submission id and the cropped answer areas, never this field.
    student_ref: str = ""
    page_paths: list[str] = Field(default_factory=list)
    status: Status = Status.received
    results: dict[str, QuestionResult] = Field(default_factory=dict)
    error: str = ""

    @property
    def total(self) -> float:
        return sum(
            (r.final_score if r.final_score is not None else r.score) for r in self.results.values()
        )

    @property
    def max_total(self) -> float:
        return sum(r.max_points for r in self.results.values())


class ReviewDecision(BaseModel):
    score: float
    comment: str = ""


class Calibration(BaseModel):
    """An instructor edit, kept so Agent 3 can learn the instructor's standard."""

    exam_id: str
    question_id: str
    transcript: str
    ai_score: float
    instructor_score: float
    comment: str = ""

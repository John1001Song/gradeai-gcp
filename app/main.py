"""Grade AI API, deployed to Cloud Run.

Instructor-facing routes:
  POST /exams                                 upload the exam config (.md)
  POST /exams/{exam_id}/submissions           upload one student's scanned pages
  GET  /exams/{exam_id}/submissions           results for the whole class
  GET  /review/queue                          items waiting for the instructor
  POST /submissions/{id}/questions/{qid}/review   confirm or adjust a score
  GET  /exams/{exam_id}/grades.csv            gradebook export
  POST /exams/{exam_id}/classroom             push approved grades to Google Classroom

Pipeline route, called by Cloud Workflows (Cloud Run IAM restricts the caller):
  POST /internal/agents/{step}
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel

from . import pipeline
from .exam_config import ExamConfigError, parse_exam_config
from .integrations import lms
from .models import Calibration, ExamConfig, ReviewDecision, Status, Submission
from .settings import settings
from .storage import blobs, state

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
app = FastAPI(title="Grade AI", version="0.1.0")
STATIC = Path(__file__).parent / "static"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _check_id(value: str, what: str) -> str:
    if not _SAFE_ID.match(value):
        raise HTTPException(400, f"{what} may use letters, digits, '-' and '_' only (max 64)")
    return value


def _exam(exam_id: str) -> ExamConfig:
    try:
        return state().get_exam(exam_id)
    except KeyError:
        raise HTTPException(404, f"No exam '{exam_id}'. Upload its config first.")


def _submission(sub_id: str) -> Submission:
    try:
        return state().get_submission(sub_id)
    except KeyError:
        raise HTTPException(404, f"No submission '{sub_id}'.")


def _view(sub: Submission) -> dict:
    data = sub.model_dump(mode="json")
    data["total"], data["max_total"] = sub.total, sub.max_total
    return data


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "mode": settings.mode}


# ---------------------------------------------------------------- exams


@app.post("/exams")
async def create_exam(exam_id: str = Form(...), config: UploadFile = File(...)) -> ExamConfig:
    _check_id(exam_id, "exam_id")
    text = (await config.read()).decode("utf-8")
    try:
        exam = parse_exam_config(text, exam_id)
    except ExamConfigError as exc:
        raise HTTPException(422, str(exc))
    blobs().put(f"configs/{exam_id}.md", text.encode(), "text/markdown")
    state().save_exam(exam)
    return exam


@app.get("/exams")
def list_exams() -> list[ExamConfig]:
    return state().list_exams()


@app.get("/exams/{exam_id}")
def get_exam(exam_id: str) -> ExamConfig:
    return _exam(exam_id)


# ---------------------------------------------------------------- submissions


@app.post("/exams/{exam_id}/submissions")
async def upload_submission(
    exam_id: str,
    background: BackgroundTasks,
    student_ref: str = Form(..., description="Roster id or email. Never sent to any agent."),
    pages: list[UploadFile] = File(...),
) -> dict:
    exam = _exam(exam_id)
    if len(pages) < exam.pages:
        raise HTTPException(422, f"This exam has {exam.pages} page(s); got {len(pages)}.")

    sub_id = uuid.uuid4().hex[:12]
    paths = []
    for i, page in enumerate(pages, start=1):
        data = await page.read()
        paths.append(blobs().put(f"uploads/{exam_id}/{sub_id}/page{i}.png", data, page.content_type or "image/png"))
    sub = Submission(id=sub_id, exam_id=exam_id, student_ref=student_ref, page_paths=paths)
    state().save_submission(sub)

    if settings.is_gcp:
        # The manifest lands last. Its finalize event fires Eventarc, which starts the
        # Cloud Workflow that calls the four agents. Agents get only the submission id.
        blobs().put(
            f"uploads/{exam_id}/{sub_id}/manifest.json",
            json.dumps({"submission_id": sub_id}).encode(),
            "application/json",
        )
    else:
        background.add_task(_run_quietly, sub_id)
    return {"submission_id": sub_id, "status": sub.status}


def _run_quietly(sub_id: str) -> None:
    try:
        pipeline.run_all(sub_id)
    except Exception:
        pass  # the failure is recorded on the submission


@app.get("/exams/{exam_id}/submissions")
def list_submissions(exam_id: str) -> list[dict]:
    _exam(exam_id)
    return [_view(s) for s in state().list_submissions(exam_id)]


@app.get("/submissions/{sub_id}")
def get_submission(sub_id: str) -> dict:
    return _view(_submission(sub_id))


@app.get("/submissions/{sub_id}/questions/{qid}/crop", include_in_schema=False)
def get_crop(sub_id: str, qid: str) -> Response:
    sub = _submission(sub_id)
    res = sub.results.get(qid)
    if not res or not res.crop_path:
        raise HTTPException(404, "No crop yet.")
    return Response(blobs().get(res.crop_path), media_type="image/png")


# ---------------------------------------------------------------- pipeline (Cloud Workflows)


class StepRequest(BaseModel):
    submission_id: str


@app.post("/internal/agents/{step}")
def run_agent(step: int, req: StepRequest) -> dict:
    if step not in pipeline.STEPS:
        raise HTTPException(404, "step must be 1-4")
    _submission(req.submission_id)
    try:
        sub = pipeline.run_step(req.submission_id, step)
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"submission_id": sub.id, "status": sub.status}


# ---------------------------------------------------------------- instructor review


@app.get("/review/queue")
def review_queue(exam_id: str | None = None) -> list[dict]:
    items = []
    for s in state().list_submissions(exam_id):
        for r in s.results.values():
            if r.route in ("review", "spot_check") and not r.reviewed:
                items.append({"submission_id": s.id, "exam_id": s.exam_id, "student_ref": s.student_ref, **r.model_dump(mode="json")})
    # Low-confidence items first, then spot checks.
    return sorted(items, key=lambda i: (i["route"] != "review", i["confidence"]))


@app.post("/submissions/{sub_id}/questions/{qid}/review")
def review(sub_id: str, qid: str, decision: ReviewDecision) -> dict:
    sub = _submission(sub_id)
    res = sub.results.get(qid)
    if res is None:
        raise HTTPException(404, f"No question '{qid}' on this submission.")
    if not 0 <= decision.score <= res.max_points:
        raise HTTPException(422, f"Score must be between 0 and {res.max_points:g}.")

    if decision.score != res.score or decision.comment:
        # Instructor edits become examples that Agent 3 reads next time.
        state().add_calibration(
            Calibration(
                exam_id=sub.exam_id,
                question_id=qid,
                transcript=res.transcript,
                ai_score=res.score,
                instructor_score=decision.score,
                comment=decision.comment,
            )
        )
    res.final_score, res.instructor_comment, res.reviewed = decision.score, decision.comment, True
    if all(r.final_score is not None for r in sub.results.values()):
        sub.status = Status.approved
    state().save_submission(sub)
    return _view(sub)


# ---------------------------------------------------------------- LMS


@app.get("/exams/{exam_id}/grades.csv")
def export_grades(exam_id: str) -> PlainTextResponse:
    exam = _exam(exam_id)
    csv_text = lms.grades_csv(exam, state().list_submissions(exam_id))
    return PlainTextResponse(
        csv_text, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{exam_id}_grades.csv"'}
    )


class ClassroomPush(BaseModel):
    course_id: str
    coursework_id: str


@app.post("/exams/{exam_id}/classroom")
def push_classroom(exam_id: str, body: ClassroomPush) -> dict:
    _exam(exam_id)
    if not settings.is_gcp:
        raise HTTPException(400, "Google Classroom sync needs GRADEAI_MODE=gcp and Classroom API credentials.")
    return lms.push_to_classroom(body.course_id, body.coursework_id, state().list_submissions(exam_id))

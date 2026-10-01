"""Parse the instructor's exam config Markdown file.

Format (see examples/phys101_midterm1.md):

    # Exam: <title>
    - course: PHYS 101
    - confidence_threshold: 0.80
    - spot_check_rate: 0.10

    ## Q1: <title> (10 pts)
    - page: 1
    - region: [x0, y0, x1, y1]      # fractions of the page, 0..1
    - prompt: ...
    - answer: ...
    ### Rubric
    - (3) <criterion> [keywords: a | b]

Only the regions listed under questions are kept. That allowlist is how
Agent 1 leaves the name and student ID header behind.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import ExamConfig, Question, RubricItem

_KV = re.compile(r"^\s*[-*]\s*([a-z_]+)\s*:\s*(.+?)\s*$")
_Q_HEAD = re.compile(r"^##\s+(Q[\w.-]*)\s*[:.\-—]\s*(.+?)\s*\((\d+(?:\.\d+)?)\s*pts?\)\s*$", re.I)
_RUBRIC = re.compile(r"^\s*[-*]\s*\((\d+(?:\.\d+)?)\)\s*(.+?)\s*(?:\[keywords:\s*(.+?)\])?\s*$", re.I)


class ExamConfigError(ValueError):
    pass


def _region(raw: str, qid: str) -> tuple[float, float, float, float]:
    nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", raw)]
    if len(nums) != 4:
        raise ExamConfigError(f"{qid}: region needs four numbers, got {raw!r}")
    x0, y0, x1, y1 = nums
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ExamConfigError(f"{qid}: region {nums} must satisfy 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1")
    return (x0, y0, x1, y1)


def parse_exam_config(text: str, exam_id: str) -> ExamConfig:
    title = exam_id
    header: dict[str, str] = {}
    questions: list[dict] = []
    current: dict | None = None
    in_rubric = False

    for line in text.splitlines():
        if line.startswith("# "):
            title = re.sub(r"^#\s+(Exam:\s*)?", "", line).strip()
            continue
        if m := _Q_HEAD.match(line):
            current = {"id": m.group(1).upper(), "title": m.group(2), "max_points": float(m.group(3)), "rubric": []}
            questions.append(current)
            in_rubric = False
            continue
        if line.startswith("### "):
            in_rubric = current is not None and "rubric" in line.lower()
            continue
        if in_rubric and current is not None and (m := _RUBRIC.match(line)):
            kws = [k.strip() for k in (m.group(3) or "").split("|") if k.strip()]
            current["rubric"].append(RubricItem(points=float(m.group(1)), description=m.group(2), keywords=kws))
            continue
        if m := _KV.match(line):
            key, val = m.group(1), m.group(2)
            (current if current is not None else header)[key] = val

    if not questions:
        raise ExamConfigError("No questions found. Each question needs a heading like '## Q1: Title (10 pts)'.")

    parsed: list[Question] = []
    for q in questions:
        qid = q["id"]
        if "region" not in q:
            raise ExamConfigError(f"{qid}: missing '- region: [x0, y0, x1, y1]'")
        rubric_total = sum(r.points for r in q["rubric"])
        if q["rubric"] and abs(rubric_total - q["max_points"]) > 1e-6:
            raise ExamConfigError(f"{qid}: rubric adds to {rubric_total} but the question is worth {q['max_points']}")
        parsed.append(
            Question(
                id=qid,
                title=q["title"],
                max_points=q["max_points"],
                page=int(q.get("page", 1)),
                region=_region(q["region"], qid),
                prompt=q.get("prompt", ""),
                answer=q.get("answer", ""),
                rubric=q["rubric"],
            )
        )

    return ExamConfig(
        exam_id=exam_id,
        title=title,
        course=header.get("course", ""),
        pages=int(header.get("pages", max(q.page for q in parsed))),
        confidence_threshold=float(header.get("confidence_threshold", 0.8)),
        spot_check_rate=float(header.get("spot_check_rate", 0.1)),
        questions=parsed,
    )


def load_exam_config(path: str | Path, exam_id: str | None = None) -> ExamConfig:
    p = Path(path)
    return parse_exam_config(p.read_text(encoding="utf-8"), exam_id or p.stem)

"""Runs the four agents in order.

Locally, `run_all` calls each agent in-process. On Google Cloud, Cloud
Workflows (infra/workflows/grading.yaml) calls POST /internal/agents/{step}
once per agent, so each step retries on its own and shows up in the
workflow's execution history.
"""

from __future__ import annotations

import logging
from typing import Callable

from .agents import agent1_prep, agent2_reader, agent3_grader, agent4_router
from .models import ExamConfig, Status, Submission
from .storage import state

log = logging.getLogger(__name__)

STEPS: dict[int, tuple[str, Callable[[Submission, ExamConfig], Submission]]] = {
    1: ("prep_and_privacy", agent1_prep.run),
    2: ("handwriting_reader", agent2_reader.run),
    3: ("grader", agent3_grader.run),
    4: ("confidence_router", agent4_router.run),
}


def run_step(submission_id: str, step: int) -> Submission:
    name, fn = STEPS[step]
    sub = state().get_submission(submission_id)
    exam = state().get_exam(sub.exam_id)
    try:
        sub = fn(sub, exam)
        sub.error = ""
    except Exception as exc:
        log.exception("step %s (%s) failed for %s", step, name, submission_id)
        sub.status, sub.error = Status.failed, f"agent {step} ({name}): {exc}"
        state().save_submission(sub)
        raise
    state().save_submission(sub)
    return sub


def run_all(submission_id: str) -> Submission:
    sub = None
    for step in STEPS:
        sub = run_step(submission_id, step)
    return sub

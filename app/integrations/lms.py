"""Send approved grades back to the LMS.

Two routes, matching the architecture's integration panel:
  - CSV export, which any LMS gradebook can import, and which also feeds Google Sheets.
  - Google Classroom API: patch each student's assignedGrade on a coursework item.

LTI 1.3 launch and grade passback (Canvas, Moodle, Blackboard) sit behind the
same interface and are on the roadmap; see docs/architecture.md.
"""

from __future__ import annotations

import csv
import io

from ..models import ExamConfig, Status, Submission


def grades_csv(exam: ExamConfig, subs: list[Submission]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["student_ref", *[f"{q.id} ({q.max_points:g})" for q in exam.questions], "total", "max", "status"])
    for s in sorted(subs, key=lambda s: s.student_ref):
        row = []
        for q in exam.questions:
            r = s.results.get(q.id)
            row.append("" if r is None else (r.final_score if r.final_score is not None else r.score))
        w.writerow([s.student_ref, *row, s.total, s.max_total, s.status.value])
    return buf.getvalue()


def push_to_classroom(course_id: str, coursework_id: str, subs: list[Submission]) -> dict[str, int]:
    """Write approved totals to Google Classroom as draft grades.

    student_ref must be the student's Classroom user id or email.
    Uses Application Default Credentials with the classroom.coursework.students scope.
    """
    from googleapiclient.discovery import build  # google-api-python-client

    svc = build("classroom", "v1", cache_discovery=False)
    subs_api = svc.courses().courseWork().studentSubmissions()
    sent = skipped = 0
    for s in subs:
        if s.status != Status.approved:
            skipped += 1
            continue
        listing = subs_api.list(courseId=course_id, courseWorkId=coursework_id, userId=s.student_ref).execute()
        for cs in listing.get("studentSubmissions", []):
            subs_api.patch(
                courseId=course_id,
                courseWorkId=coursework_id,
                id=cs["id"],
                updateMask="draftGrade",
                body={"draftGrade": s.total},
            ).execute()
            sent += 1
    return {"sent": sent, "skipped_not_approved": skipped}

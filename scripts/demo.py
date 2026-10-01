"""End-to-end demo in mock mode: upload the config, grade three students,
print the routes, then approve the review queue as an instructor would.

    python scripts/demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

EXAM = "phys101-mt1"


def main() -> None:
    scans = sorted((ROOT / "examples" / "scans").glob("*_page1.png"))
    if not scans:
        sys.exit("No sample scans. Run: python scripts/make_sample_exams.py")

    c = TestClient(app)
    with open(ROOT / "examples" / "phys101_midterm1.md", "rb") as f:
        r = c.post("/exams", data={"exam_id": EXAM}, files={"config": ("phys101_midterm1.md", f, "text/markdown")})
    r.raise_for_status()
    print(f"Exam loaded: {r.json()['title']} ({len(r.json()['questions'])} questions)\n")

    for scan in scans:
        student = scan.name.split("_page")[0]
        with open(scan, "rb") as f:
            c.post(f"/exams/{EXAM}/submissions", data={"student_ref": student}, files={"pages": (scan.name, f, "image/png")}).raise_for_status()

    for s in c.get(f"/exams/{EXAM}/submissions").json():
        print(f"{s['student_ref']:<14} {s['total']:>5}/{s['max_total']:<4} {s['status']}")
        for qid, r in s["results"].items():
            print(f"   {qid}: {r['score']:>4}/{r['max_points']:<4} conf {r['confidence']:.2f}  {r['route']:<12} {r['route_reason']}")

    queue = c.get("/review/queue", params={"exam_id": EXAM}).json()
    print(f"\nReview queue: {len(queue)} item(s). Instructor confirms each one...")
    for item in queue:
        c.post(f"/submissions/{item['submission_id']}/questions/{item['question_id']}/review", json={"score": item["score"]})

    print("\n" + c.get(f"/exams/{EXAM}/grades.csv").text)


if __name__ == "__main__":
    main()

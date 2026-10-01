import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from app.agents.agent1_prep import crop_region  # noqa: E402
from app.exam_config import ExamConfigError, load_exam_config, parse_exam_config  # noqa: E402
from app.main import app  # noqa: E402
from make_sample_exams import STUDENTS, make_page  # noqa: E402

CONFIG = ROOT / "examples" / "phys101_midterm1.md"


def _png(student_key: str) -> bytes:
    img, meta = make_page(STUDENTS[student_key])
    buf = io.BytesIO()
    img.save(buf, format="PNG", pnginfo=meta)
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    c = TestClient(app)
    with open(CONFIG, "rb") as f:
        c.post("/exams", data={"exam_id": "mt1"}, files={"config": ("c.md", f)}).raise_for_status()
    return c


def _submit(client, key):
    r = client.post("/exams/mt1/submissions", data={"student_ref": key}, files={"pages": ("p.png", _png(key), "image/png")})
    r.raise_for_status()
    return client.get(f"/submissions/{r.json()['submission_id']}").json()


# ---------------------------------------------------------------- exam config


def test_config_parses_questions_and_rubric():
    exam = load_exam_config(CONFIG, "mt1")
    assert [q.id for q in exam.questions] == ["Q1", "Q2"]
    assert exam.question("Q1").region == (0.05, 0.18, 0.95, 0.55)
    assert sum(r.points for r in exam.question("Q2").rubric) == 10
    assert exam.confidence_threshold == 0.8


def test_config_rejects_rubric_that_does_not_add_up():
    bad = "# Exam: X\n## Q1: A (10 pts)\n- region: [0,0,1,1]\n### Rubric\n- (3) step\n"
    with pytest.raises(ExamConfigError, match="adds to 3"):
        parse_exam_config(bad, "x")


def test_config_rejects_bad_region():
    with pytest.raises(ExamConfigError, match="region"):
        parse_exam_config("## Q1: A (5 pts)\n- region: [0.5, 0, 0.2, 1]\n", "x")


# ---------------------------------------------------------------- agent 1 privacy


def test_crops_never_include_the_name_header():
    """The header sits in the top 12% of the page; no answer region may touch it."""
    exam = load_exam_config(CONFIG, "mt1")
    page = Image.open(io.BytesIO(_png("s001_alvarez"))).convert("RGB")
    header_bottom = int(0.12 * page.height)
    for q in exam.questions:
        assert q.region[1] * page.height > header_bottom
        crop = crop_region(page, q.region)
        assert crop.height < page.height


def test_crop_metadata_carries_only_its_own_answer(client):
    sub = _submit(client, "s001_alvarez")
    crop = client.get(f"/submissions/{sub['id']}/questions/Q1/crop").content
    info = Image.open(io.BytesIO(crop)).info
    assert "Alvarez" not in str(info)
    assert "35.3" in info["mock_transcript"]


# ---------------------------------------------------------------- agents 2-4


def test_correct_answers_are_auto_approved_or_spot_checked(client):
    sub = _submit(client, "s001_alvarez")
    assert sub["total"] == 20
    assert {r["route"] for r in sub["results"].values()} <= {"auto_approve", "spot_check"}


def test_partial_answer_goes_to_review(client):
    sub = _submit(client, "s002_chen")
    assert sub["results"]["Q2"]["route"] == "review"
    assert 0 < sub["results"]["Q2"]["score"] < 10


def test_prompt_injection_is_blocked_and_routed_to_instructor(client):
    sub = _submit(client, "s003_okafor")
    q2 = sub["results"]["Q2"]
    assert q2["injection_blocked"] is True
    assert q2["score"] == 0 and q2["route"] == "review"


# ---------------------------------------------------------------- instructor review + LMS


def test_instructor_edit_finalizes_and_calibrates(client):
    sub = _submit(client, "s002_chen")
    r = client.post(f"/submissions/{sub['id']}/questions/Q2/review", json={"score": 9, "comment": "Method is right"})
    assert r.status_code == 200
    assert r.json()["results"]["Q2"]["final_score"] == 9

    from app.storage import state

    assert any(c.instructor_score == 9 for c in state().calibrations("mt1", "Q2"))


def test_review_rejects_out_of_range_score(client):
    sub = _submit(client, "s002_chen")
    r = client.post(f"/submissions/{sub['id']}/questions/Q2/review", json={"score": 11})
    assert r.status_code == 422


def test_grades_csv_export(client):
    _submit(client, "s001_alvarez")
    csv_text = client.get("/exams/mt1/grades.csv").text
    assert csv_text.splitlines()[0].startswith("student_ref,Q1 (10),Q2 (10)")
    assert "s001_alvarez" in csv_text

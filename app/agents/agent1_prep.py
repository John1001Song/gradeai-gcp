"""Agent 1: Prep & Privacy.

Reads the instructor's exam config and keeps only the answer areas it lists.
The name and student ID header is never in an answer area, so it is never
cropped, stored as a crop, or sent to a model.

A Sensitive Data Protection scan runs on each crop as a backup, in case a
student writes a name inside an answer area. Anything it finds is blacked out.
"""

from __future__ import annotations

import io
import logging

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from ..models import ExamConfig, QuestionResult, Status, Submission
from ..settings import settings
from ..storage import blobs

log = logging.getLogger(__name__)

# Info types the backup scan looks for in a cropped answer area.
PII_INFO_TYPES = ["PERSON_NAME", "EMAIL_ADDRESS", "PHONE_NUMBER", "US_SOCIAL_SECURITY_NUMBER"]


def crop_region(page: Image.Image, region: tuple[float, float, float, float]) -> Image.Image:
    w, h = page.size
    x0, y0, x1, y1 = region
    box = (round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h))
    return page.crop(box)


def _png(img: Image.Image, mock_transcript: str | None = None) -> bytes:
    buf = io.BytesIO()
    meta = None
    if mock_transcript is not None:
        # Mock mode only: carry the sample's known answer text to the mock reader,
        # since there is no OCR service locally. Real crops carry no metadata.
        meta = PngInfo()
        meta.add_text("mock_transcript", mock_transcript)
    img.convert("RGB").save(buf, format="PNG", pnginfo=meta)
    return buf.getvalue()


def _dlp_redact(png: bytes) -> tuple[bytes, bool]:
    """Black out PII that Sensitive Data Protection finds in an image."""
    from google.cloud import dlp_v2

    from ..gcp.clients import dlp_client

    info_types = [{"name": t} for t in PII_INFO_TYPES]
    resp = dlp_client().redact_image(
        request={
            "parent": f"projects/{settings.project_id}/locations/global",
            "inspect_config": {
                "info_types": info_types,
                "min_likelihood": dlp_v2.Likelihood.LIKELY,
                "include_quote": False,
            },
            "image_redaction_configs": [{"info_type": t, "redaction_color": {}} for t in info_types],
            "byte_item": {"type_": dlp_v2.ByteContentItem.BytesType.IMAGE_PNG, "data": png},
        }
    )
    changed = resp.redacted_image != png
    return resp.redacted_image, changed


def run(sub: Submission, exam: ExamConfig) -> Submission:
    pages = [Image.open(io.BytesIO(blobs().get(p))) for p in sub.page_paths]
    if len(pages) < exam.pages:
        raise ValueError(f"exam has {exam.pages} page(s) but submission has {len(pages)}")

    for q in exam.questions:
        page = pages[q.page - 1]
        mock_text = None if settings.is_gcp else page.info.get(f"mock_transcript_{q.id}")
        crop = _png(crop_region(page, q.region), mock_text)
        redacted = False
        if settings.is_gcp and settings.dlp_backup_scan:
            crop, redacted = _dlp_redact(crop)
        path = blobs().put(f"crops/{sub.exam_id}/{sub.id}/{q.id}.png", crop, "image/png")
        sub.results[q.id] = QuestionResult(
            question_id=q.id, crop_path=path, pii_redacted=redacted, max_points=q.max_points
        )
        log.info("agent1 %s %s cropped region=%s redacted=%s", sub.id, q.id, q.region, redacted)

    sub.status = Status.cropped
    return sub

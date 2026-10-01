"""Agent 2: Handwriting Reader.

Turns each cropped answer area into text, with math written as LaTeX.
Everything runs through managed Google Cloud APIs; nothing is self-hosted.

  1. Document AI OCR API reads the handwriting and returns a confidence.
  2. Gemini on Vertex AI looks at the same crop plus the OCR text and writes
     a clean transcript, fixing math notation, subscripts, and units.
"""

from __future__ import annotations

import io
import json
import logging

from PIL import Image

from ..models import ExamConfig, Status, Submission
from ..settings import settings
from ..storage import blobs

log = logging.getLogger(__name__)

TRANSCRIBE_PROMPT = """You are transcribing a student's handwritten answer to a STEM exam question.
Question: {prompt}

An OCR pass produced this draft (it may garble math):
---
{ocr_text}
---

Write exactly what the student wrote, in reading order. Use LaTeX for math.
Do not correct the student's mistakes and do not solve the problem.
Return JSON: {{"transcript": str, "legibility": float between 0 and 1}}"""


def _docai_ocr(png: bytes) -> tuple[str, float]:
    from google.cloud import documentai

    from ..gcp.clients import docai_client

    result = docai_client().process_document(
        request=documentai.ProcessRequest(
            name=settings.docai_processor,
            raw_document=documentai.RawDocument(content=png, mime_type="image/png"),
        )
    )
    doc = result.document
    confs = [t.layout.confidence for p in doc.pages for t in p.tokens if t.layout.confidence]
    return doc.text, (sum(confs) / len(confs)) if confs else 0.0


def _gemini_transcribe(png: bytes, prompt: str, ocr_text: str) -> tuple[str, float]:
    from google.genai import types

    from ..gcp.clients import genai_client

    resp = genai_client().models.generate_content(
        model=settings.reader_model,
        contents=[
            types.Part.from_bytes(data=png, mime_type="image/png"),
            TRANSCRIBE_PROMPT.format(prompt=prompt, ocr_text=ocr_text or "(empty)"),
        ],
        config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json"),
    )
    data = json.loads(resp.text)
    return data.get("transcript", ""), float(data.get("legibility", 0.0))


def _mock_read(png: bytes) -> tuple[str, float]:
    text = Image.open(io.BytesIO(png)).info.get("mock_transcript", "")
    return text, (0.95 if text else 0.0)


def run(sub: Submission, exam: ExamConfig) -> Submission:
    for q in exam.questions:
        res = sub.results[q.id]
        png = blobs().get(res.crop_path)
        if settings.is_gcp:
            ocr_text, ocr_conf = _docai_ocr(png)
            transcript, legibility = _gemini_transcribe(png, q.prompt, ocr_text)
            res.ocr_confidence = round(min(ocr_conf, legibility) if ocr_text else legibility, 3)
        else:
            transcript, res.ocr_confidence = _mock_read(png)
        res.transcript = transcript
        log.info("agent2 %s %s chars=%d conf=%.2f", sub.id, q.id, len(transcript), res.ocr_confidence)

    sub.status = Status.transcribed
    return sub

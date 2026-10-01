"""Blob storage for scans and crops, plus the state store for submissions.

mock mode: files under GRADEAI_DATA_DIR and an in-memory dict.
gcp mode:  Cloud Storage (bucket encrypted with a CMEK key) and Firestore.
"""

from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from .models import Calibration, ExamConfig, Submission
from .settings import settings


# ---------------------------------------------------------------- blobs


class BlobStore(Protocol):
    def put(self, path: str, data: bytes, content_type: str = "application/octet-stream") -> str: ...
    def get(self, path: str) -> bytes: ...


class LocalBlobStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, path: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return path

    def get(self, path: str) -> bytes:
        return (self.root / path).read_bytes()


class GcsBlobStore:
    """Cloud Storage. CMEK is set as the bucket's default key in Terraform,
    so every object written here is encrypted with the school's key."""

    def __init__(self, bucket: str):
        from google.cloud import storage  # imported lazily so mock mode needs no GCP libs

        self.bucket = storage.Client(project=settings.project_id or None).bucket(bucket)

    def put(self, path: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self.bucket.blob(path).upload_from_string(data, content_type=content_type)
        return path

    def get(self, path: str) -> bytes:
        return self.bucket.blob(path).download_as_bytes()


# ---------------------------------------------------------------- state


class StateStore(Protocol):
    def save_exam(self, exam: ExamConfig) -> None: ...
    def get_exam(self, exam_id: str) -> ExamConfig: ...
    def list_exams(self) -> list[ExamConfig]: ...
    def save_submission(self, sub: Submission) -> None: ...
    def get_submission(self, sub_id: str) -> Submission: ...
    def list_submissions(self, exam_id: str | None = None) -> list[Submission]: ...
    def add_calibration(self, cal: Calibration) -> None: ...
    def calibrations(self, exam_id: str, question_id: str, limit: int = 5) -> list[Calibration]: ...


class MemoryStateStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.exams: dict[str, ExamConfig] = {}
        self.subs: dict[str, Submission] = {}
        self.cals: list[Calibration] = []

    def save_exam(self, exam: ExamConfig) -> None:
        with self._lock:
            self.exams[exam.exam_id] = exam.model_copy(deep=True)

    def get_exam(self, exam_id: str) -> ExamConfig:
        return self.exams[exam_id].model_copy(deep=True)

    def list_exams(self) -> list[ExamConfig]:
        return [e.model_copy(deep=True) for e in self.exams.values()]

    def save_submission(self, sub: Submission) -> None:
        with self._lock:
            self.subs[sub.id] = sub.model_copy(deep=True)

    def get_submission(self, sub_id: str) -> Submission:
        return self.subs[sub_id].model_copy(deep=True)

    def list_submissions(self, exam_id: str | None = None) -> list[Submission]:
        return [s.model_copy(deep=True) for s in self.subs.values() if exam_id in (None, s.exam_id)]

    def add_calibration(self, cal: Calibration) -> None:
        with self._lock:
            self.cals.append(cal)

    def calibrations(self, exam_id: str, question_id: str, limit: int = 5) -> list[Calibration]:
        hits = [c for c in self.cals if c.exam_id == exam_id and c.question_id == question_id]
        return hits[-limit:]


class FirestoreStateStore:
    def __init__(self) -> None:
        from google.cloud import firestore

        self.db = firestore.Client(project=settings.project_id or None)

    def save_exam(self, exam: ExamConfig) -> None:
        self.db.collection("exams").document(exam.exam_id).set(exam.model_dump(mode="json"))

    def get_exam(self, exam_id: str) -> ExamConfig:
        doc = self.db.collection("exams").document(exam_id).get()
        if not doc.exists:
            raise KeyError(exam_id)
        return ExamConfig.model_validate(doc.to_dict())

    def list_exams(self) -> list[ExamConfig]:
        return [ExamConfig.model_validate(d.to_dict()) for d in self.db.collection("exams").stream()]

    def save_submission(self, sub: Submission) -> None:
        self.db.collection("submissions").document(sub.id).set(sub.model_dump(mode="json"))

    def get_submission(self, sub_id: str) -> Submission:
        doc = self.db.collection("submissions").document(sub_id).get()
        if not doc.exists:
            raise KeyError(sub_id)
        return Submission.model_validate(doc.to_dict())

    def list_submissions(self, exam_id: str | None = None) -> list[Submission]:
        q = self.db.collection("submissions")
        if exam_id:
            q = q.where("exam_id", "==", exam_id)
        return [Submission.model_validate(d.to_dict()) for d in q.stream()]

    def add_calibration(self, cal: Calibration) -> None:
        self.db.collection("calibrations").add(cal.model_dump(mode="json"))

    def calibrations(self, exam_id: str, question_id: str, limit: int = 5) -> list[Calibration]:
        q = (
            self.db.collection("calibrations")
            .where("exam_id", "==", exam_id)
            .where("question_id", "==", question_id)
            .limit(limit)
        )
        return [Calibration.model_validate(d.to_dict()) for d in q.stream()]


@lru_cache
def blobs() -> BlobStore:
    if settings.is_gcp:
        return GcsBlobStore(settings.bucket)
    return LocalBlobStore(settings.local_data_dir / "blobs")


@lru_cache
def state() -> StateStore:
    return FirestoreStateStore() if settings.is_gcp else MemoryStateStore()

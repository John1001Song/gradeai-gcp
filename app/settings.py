"""Runtime settings, read from environment variables.

GRADEAI_MODE=mock (default) runs everything locally with no Google Cloud
credentials: files on disk, an in-memory store, and deterministic stand-ins
for the AI services. GRADEAI_MODE=gcp switches every agent to the real
Google Cloud APIs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    mode: str = field(default_factory=lambda: _env("GRADEAI_MODE", "mock"))

    # Google Cloud project and locations
    project_id: str = field(default_factory=lambda: _env("GOOGLE_CLOUD_PROJECT"))
    region: str = field(default_factory=lambda: _env("GRADEAI_REGION", "us-central1"))

    # Storage
    bucket: str = field(default_factory=lambda: _env("GRADEAI_BUCKET"))
    local_data_dir: Path = field(
        default_factory=lambda: Path(_env("GRADEAI_DATA_DIR", ".data")).resolve()
    )

    # Agent 2: Document AI OCR processor (projects/.../locations/us/processors/...)
    docai_processor: str = field(default_factory=lambda: _env("GRADEAI_DOCAI_PROCESSOR"))
    docai_location: str = field(default_factory=lambda: _env("GRADEAI_DOCAI_LOCATION", "us"))

    # Gemini models on Vertex AI
    reader_model: str = field(default_factory=lambda: _env("GRADEAI_READER_MODEL", "gemini-2.5-flash"))
    grader_model: str = field(default_factory=lambda: _env("GRADEAI_GRADER_MODEL", "gemini-2.5-pro"))
    router_model: str = field(default_factory=lambda: _env("GRADEAI_ROUTER_MODEL", "gemini-2.5-flash"))

    # Agent 3: Model Armor template (projects/.../locations/.../templates/...)
    model_armor_template: str = field(default_factory=lambda: _env("GRADEAI_MODEL_ARMOR_TEMPLATE"))

    # Agent 1: run the Sensitive Data Protection backup scan on cropped regions
    dlp_backup_scan: bool = field(
        default_factory=lambda: _env("GRADEAI_DLP_BACKUP_SCAN", "true").lower() == "true"
    )

    @property
    def is_gcp(self) -> bool:
        return self.mode == "gcp"


settings = Settings()

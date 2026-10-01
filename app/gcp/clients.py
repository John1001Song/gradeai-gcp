"""Lazily built Google Cloud clients. Only imported in GRADEAI_MODE=gcp."""

from __future__ import annotations

from functools import lru_cache

from ..settings import settings


@lru_cache
def genai_client():
    """Gemini on Vertex AI through the Google Gen AI SDK."""
    from google import genai

    return genai.Client(vertexai=True, project=settings.project_id, location=settings.region)


@lru_cache
def docai_client():
    from google.api_core.client_options import ClientOptions
    from google.cloud import documentai

    opts = ClientOptions(api_endpoint=f"{settings.docai_location}-documentai.googleapis.com")
    return documentai.DocumentProcessorServiceClient(client_options=opts)


@lru_cache
def dlp_client():
    from google.cloud import dlp_v2

    return dlp_v2.DlpServiceClient()


@lru_cache
def model_armor_client():
    from google.api_core.client_options import ClientOptions
    from google.cloud import modelarmor_v1

    # Template path: projects/<p>/locations/<loc>/templates/<id>
    location = settings.model_armor_template.split("/")[3]
    opts = ClientOptions(api_endpoint=f"modelarmor.{location}.rep.googleapis.com")
    return modelarmor_v1.ModelArmorClient(transport="rest", client_options=opts)

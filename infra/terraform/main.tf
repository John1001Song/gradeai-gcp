terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_project" "this" {}

locals {
  services = [
    "run.googleapis.com",
    "workflows.googleapis.com",
    "eventarc.googleapis.com",
    "pubsub.googleapis.com",
    "storage.googleapis.com",
    "firestore.googleapis.com",
    "cloudkms.googleapis.com",
    "aiplatform.googleapis.com",
    "documentai.googleapis.com",
    "dlp.googleapis.com",
    "modelarmor.googleapis.com",
    "classroom.googleapis.com",
    "artifactregistry.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.services)
  service            = each.value
  disable_on_destroy = false
}

# ---------------------------------------------------------------- CMEK

resource "google_kms_key_ring" "gradeai" {
  name       = "gradeai"
  location   = var.region
  depends_on = [google_project_service.apis]
}

resource "google_kms_crypto_key" "data" {
  name            = "student-data"
  key_ring        = google_kms_key_ring.gradeai.id
  rotation_period = "7776000s" # 90 days
}

data "google_storage_project_service_account" "gcs" {}

resource "google_kms_crypto_key_iam_member" "gcs_uses_key" {
  crypto_key_id = google_kms_crypto_key.data.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${data.google_storage_project_service_account.gcs.email_address}"
}

# ---------------------------------------------------------------- storage

resource "google_storage_bucket" "exams" {
  name                        = "${var.project_id}-gradeai-exams"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  encryption {
    default_kms_key_name = google_kms_crypto_key.data.id
  }

  lifecycle_rule {
    condition { age = 365 }
    action { type = "Delete" }
  }

  depends_on = [google_kms_crypto_key_iam_member.gcs_uses_key]
}

resource "google_firestore_database" "default" {
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"
  depends_on  = [google_project_service.apis]
}

# ---------------------------------------------------------------- Document AI (Agent 2)

resource "google_document_ai_processor" "ocr" {
  location     = var.docai_location
  display_name = "gradeai-handwriting-ocr"
  type         = "OCR_PROCESSOR"
  depends_on   = [google_project_service.apis]
}

# ---------------------------------------------------------------- service accounts (least privilege)

resource "google_service_account" "api" {
  account_id   = "gradeai-api"
  display_name = "Grade AI API and agents (Cloud Run)"
}

resource "google_service_account" "workflow" {
  account_id   = "gradeai-workflow"
  display_name = "Grade AI grading workflow"
}

resource "google_service_account" "eventarc" {
  account_id   = "gradeai-eventarc"
  display_name = "Grade AI upload trigger"
}

resource "google_storage_bucket_iam_member" "api_objects" {
  bucket = google_storage_bucket.exams.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.api.email}"
}

resource "google_storage_bucket_iam_member" "workflow_reads_manifest" {
  bucket = google_storage_bucket.exams.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.workflow.email}"
}

resource "google_project_iam_member" "api_roles" {
  for_each = toset([
    "roles/datastore.user",        # Firestore
    "roles/aiplatform.user",       # Gemini on Vertex AI
    "roles/documentai.apiUser",    # Document AI OCR
    "roles/dlp.user",              # Sensitive Data Protection backup scan
    "roles/modelarmor.user",       # Model Armor screening
    "roles/logging.logWriter",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.api.email}"
}

resource "google_project_iam_member" "workflow_logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.workflow.email}"
}

resource "google_project_iam_member" "eventarc_roles" {
  for_each = toset(["roles/eventarc.eventReceiver", "roles/workflows.invoker"])
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.eventarc.email}"
}

# Cloud Storage publishes finalize events through Pub/Sub for Eventarc.
resource "google_project_iam_member" "gcs_pubsub" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_storage_project_service_account.gcs.email_address}"
}

# ---------------------------------------------------------------- Cloud Run

resource "google_cloud_run_v2_service" "api" {
  name                = "gradeai-api"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.api.email
    timeout         = "300s"
    scaling {
      min_instance_count = 0
      max_instance_count = 50
    }
    containers {
      image = var.image
      resources {
        limits = { cpu = "1", memory = "1Gi" }
      }
      env {
        name  = "GRADEAI_MODE"
        value = "gcp"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GRADEAI_REGION"
        value = var.region
      }
      env {
        name  = "GRADEAI_BUCKET"
        value = google_storage_bucket.exams.name
      }
      env {
        name  = "GRADEAI_DOCAI_PROCESSOR"
        value = google_document_ai_processor.ocr.id
      }
      env {
        name  = "GRADEAI_DOCAI_LOCATION"
        value = var.docai_location
      }
      env {
        name  = "GRADEAI_MODEL_ARMOR_TEMPLATE"
        value = var.model_armor_template
      }
    }
  }

  depends_on = [google_project_service.apis, google_firestore_database.default]
}

resource "google_cloud_run_v2_service_iam_member" "workflow_invokes_api" {
  name     = google_cloud_run_v2_service.api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.workflow.email}"
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  count    = var.allow_public_ui ? 1 : 0
  name     = google_cloud_run_v2_service.api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ---------------------------------------------------------------- Workflows + Eventarc

resource "google_workflows_workflow" "grading" {
  name            = "gradeai-grading"
  region          = var.region
  service_account = google_service_account.workflow.id
  source_contents = file("${path.module}/../workflows/grading.yaml")
  user_env_vars = {
    GRADEAI_SERVICE_URL = google_cloud_run_v2_service.api.uri
  }
}

resource "google_eventarc_trigger" "uploads" {
  name            = "gradeai-uploads"
  location        = var.region
  service_account = google_service_account.eventarc.email

  matching_criteria {
    attribute = "type"
    value     = "google.cloud.storage.object.v1.finalized"
  }
  matching_criteria {
    attribute = "bucket"
    value     = google_storage_bucket.exams.name
  }

  destination {
    workflow = google_workflows_workflow.grading.id
  }

  depends_on = [google_project_iam_member.gcs_pubsub, google_project_iam_member.eventarc_roles]
}

output "api_url" {
  value = google_cloud_run_v2_service.api.uri
}

output "bucket" {
  value = google_storage_bucket.exams.name
}

output "docai_processor" {
  value = google_document_ai_processor.ocr.id
}

output "kms_key" {
  value = google_kms_crypto_key.data.id
}

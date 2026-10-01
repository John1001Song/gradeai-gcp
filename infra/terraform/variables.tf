variable "project_id" {
  description = "Google Cloud project id"
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Workflows, Eventarc, and the bucket"
  type        = string
  default     = "us-central1"
}

variable "image" {
  description = "Container image for the API, e.g. us-central1-docker.pkg.dev/<project>/gradeai/api:latest"
  type        = string
}

variable "docai_location" {
  description = "Document AI location (us or eu)"
  type        = string
  default     = "us"
}

variable "model_armor_template" {
  description = "Full Model Armor template name. Leave empty to use the built-in pattern check."
  type        = string
  default     = ""
}

variable "allow_public_ui" {
  description = "Let anyone reach the Cloud Run URL. Keep false and put IAP in front for real schools."
  type        = bool
  default     = false
}

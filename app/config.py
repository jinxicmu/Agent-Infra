import os
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent

HOSTING_MODE = os.environ.get("HOSTING_MODE", "runpod")

AI_STUDIO_API_KEY = os.environ["AI_STUDIO_API_KEY"]

COMFY_BASE_URL = os.environ.get("COMFY_BASE_URL", "http://127.0.0.1:8188")
COMFY_INPUT_DIR = Path(os.environ.get("COMFY_INPUT_DIR", "/workspace/runpod-slim/ComfyUI/input"))
COMFY_OUTPUT_DIR = Path(os.environ.get("COMFY_OUTPUT_DIR", "/workspace/runpod-slim/ComfyUI/output"))

GCP_PROJECT = os.environ.get("GCP_PROJECT", "novvy-dev")
GCS_OUTPUT_BUCKET = os.environ.get("GCS_OUTPUT_BUCKET", "self_deployed_model_working_dir")
GCS_OUTPUT_PREFIX = os.environ.get("GCS_OUTPUT_PREFIX", "generated_video_dir")
GCS_IMPERSONATE_SERVICE_ACCOUNT = os.environ.get(
    "GCS_IMPERSONATE_SERVICE_ACCOUNT",
    "ai-studio-h3-hosting@novvy-dev.iam.gserviceaccount.com",
)

KEEP_LOCAL_OUTPUTS = os.environ.get("KEEP_LOCAL_OUTPUTS", "true").lower() == "true"

MAX_PENDING_REALTIME = int(os.environ.get("MAX_PENDING_REALTIME", "20"))
MAX_PENDING_BATCH = int(os.environ.get("MAX_PENDING_BATCH", "200"))
MAX_TOTAL_PENDING = int(os.environ.get("MAX_TOTAL_PENDING", "220"))
MAX_COMFY_ACTIVE = int(os.environ.get("MAX_COMFY_ACTIVE", "2"))

MAX_INPUT_IMAGE_MB = int(os.environ.get("MAX_INPUT_IMAGE_MB", "20"))
IMAGE_DOWNLOAD_TIMEOUT_SECONDS = int(os.environ.get("IMAGE_DOWNLOAD_TIMEOUT_SECONDS", "20"))
MAX_IMAGE_REDIRECTS = int(os.environ.get("MAX_IMAGE_REDIRECTS", "3"))

LOG_PROMPTS = os.environ.get("LOG_PROMPTS", "false").lower() == "true"
JOB_RETENTION_HOURS = int(os.environ.get("JOB_RETENTION_HOURS", "168"))
DISPATCHER_POLL_INTERVAL_SECONDS = float(os.environ.get("DISPATCHER_POLL_INTERVAL_SECONDS", "2"))

JOBS_DIR = API_ROOT / "jobs"
WORKFLOWS_DIR = API_ROOT / "workflows"
LOGS_DIR = API_ROOT / "logs"

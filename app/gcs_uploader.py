import google.auth
from google.auth import impersonated_credentials
from google.cloud import storage

from app import config

_client: storage.Client | None = None


def _get_client() -> storage.Client:
    global _client
    if _client is not None:
        return _client

    source_credentials, _ = google.auth.default()
    target_credentials = impersonated_credentials.Credentials(
        source_credentials=source_credentials,
        target_principal=config.GCS_IMPERSONATE_SERVICE_ACCOUNT,
        target_scopes=["https://www.googleapis.com/auth/devstorage.read_write"],
        lifetime=3600,
    )
    _client = storage.Client(project=config.GCP_PROJECT, credentials=target_credentials)
    return _client


def upload_video(local_path: str, task_id: str) -> tuple[str, str, str]:
    """Uploads local_path to gs://<bucket>/<prefix>/<task_id>.mp4, verifies it exists.

    Returns (gcs_uri, bucket, object_name). Raises on failure.
    """
    client = _get_client()
    bucket = client.bucket(config.GCS_OUTPUT_BUCKET)
    object_name = f"{config.GCS_OUTPUT_PREFIX}/{task_id}.mp4"
    blob = bucket.blob(object_name)

    blob.upload_from_filename(local_path, content_type="video/mp4")

    blob.reload()
    if not blob.exists():
        raise RuntimeError(f"GCS upload verification failed for {object_name}")

    gcs_uri = f"gs://{config.GCS_OUTPUT_BUCKET}/{object_name}"
    return gcs_uri, config.GCS_OUTPUT_BUCKET, object_name

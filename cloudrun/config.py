import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _positive_int(name, default):
    raw = os.getenv(name, '').strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f'{name} must be a positive integer, got {raw!r}') from None
    if value < 1:
        raise ValueError(f'{name} must be a positive integer, got {raw!r}')
    return value


@dataclass
class Settings:
    project: str = 'novvy-dev'
    database: str = '(default)'
    revision: str = ''
    clients: dict = field(default_factory=dict)
    workers: dict = field(default_factory=dict)
    bucket: str = 'self_deployed_model_working_dir'
    prefix: str = 'generated_video_dir'
    lease_seconds: int = 120
    task_seconds: int = 1800
    realtime_limit: int = 20
    batch_limit: int = 200
    total_limit: int = 220
    client_rpm: int = 60
    scheduler_email: str = ''
    scheduler_audience: str = ''
    accept_submissions: bool = True

    @classmethod
    def from_env(cls):
        manifest = json.loads((Path(__file__).resolve().parents[1] / 'workflows/CAPABILITIES.json').read_text())
        settings = cls(
            accept_submissions=os.getenv('ACCEPT_SUBMISSIONS', 'true').lower() == 'true',
            project=os.getenv('GCP_PROJECT', 'novvy-dev'),
            database=os.getenv('FIRESTORE_DATABASE', '(default)'),
            revision=manifest['revision'],
            clients=json.loads(os.environ['CLIENT_API_KEYS_JSON']),
            workers=json.loads(os.environ['WORKER_API_KEYS_JSON']),
            bucket=os.getenv('GCS_OUTPUT_BUCKET', 'self_deployed_model_working_dir'),
            prefix=os.getenv('GCS_OUTPUT_PREFIX', 'generated_video_dir').strip('/'),
            scheduler_email=os.environ['SCHEDULER_SERVICE_ACCOUNT'],
            scheduler_audience=os.environ['SCHEDULER_AUDIENCE'],
            # Admission limits are deployment capacity, not code: size them to the worker fleet.
            realtime_limit=_positive_int('REALTIME_QUEUE_LIMIT', cls.realtime_limit),
            batch_limit=_positive_int('BATCH_QUEUE_LIMIT', cls.batch_limit),
            total_limit=_positive_int('TOTAL_QUEUE_LIMIT', cls.total_limit),
            client_rpm=_positive_int('CLIENT_RPM', cls.client_rpm),
        )
        keys = list(settings.clients.values()) + list(settings.workers.values())
        if not settings.clients or not settings.workers or any(not isinstance(k, str) or len(k) < 32 for k in keys):
            raise ValueError('Configure nonempty client/worker key maps with secrets of at least 32 characters')
        if len(set(keys)) != len(keys):
            raise ValueError('Each client and worker needs a distinct credential')
        if settings.total_limit < max(settings.realtime_limit, settings.batch_limit):
            raise ValueError('TOTAL_QUEUE_LIMIT must be at least the larger of the realtime and batch limits')
        return settings

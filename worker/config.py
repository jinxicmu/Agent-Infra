import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass
class Settings:
    worker_id: str
    cloud_url: str
    api_key: str
    comfy_url: str
    state_dir: Path
    input_dir: Path
    output_dir: Path
    workflow_dir: Path
    manifest: dict
    project: str = 'novvy-dev'
    impersonate: str = ''
    auth_mode: str = 'adc'
    gcloud_account: str = ''
    poll_seconds: float = 1.0
    min_free_bytes: int = 5 * 1024**3

    @classmethod
    def from_env(cls):
        root = Path(__file__).resolve().parents[1]
        workflow_dir = root / 'workflows'
        manifest = json.loads((workflow_dir/'CAPABILITIES.json').read_text())
        if hashlib.sha256(json.dumps(manifest['files'], sort_keys=True).encode()).hexdigest() != manifest['revision']:
            raise ValueError('Manifest revision does not match its artifact hashes')
        for filename, checksum in manifest['files'].items():
            if hashlib.sha256((workflow_dir/filename).read_bytes()).hexdigest() != checksum:
                raise ValueError(f'Workflow artifact changed: {filename}; publish a new manifest')
        worker_id = os.environ['WORKER_ID']
        state = Path(os.environ['WORKER_STATE_DIR']).resolve()
        cloud_url = os.environ['CLOUD_RUN_URL'].rstrip('/')
        comfy = os.environ['COMFY_BASE_URL'].rstrip('/')
        url = urlparse(cloud_url)
        if url.scheme != 'https' or not url.hostname or url.username or url.query or url.fragment:
            raise ValueError('CLOUD_RUN_URL must be a clean HTTPS service URL')
        local = urlparse(comfy)
        if local.scheme != 'http' or local.hostname != '127.0.0.1' or local.path or local.username:
            raise ValueError('ComfyUI must use http://127.0.0.1:<port>')
        input_dir = Path(os.environ['COMFY_INPUT_DIR']).resolve()
        output_dir = Path(os.environ['COMFY_OUTPUT_DIR']).resolve()
        if len({state, input_dir, output_dir}) != 3:
            raise ValueError('Use distinct state/input/output directories for each worker')
        for path in (state, input_dir, output_dir):
            path.mkdir(parents=True, exist_ok=True)
        return cls(worker_id, cloud_url, os.environ['WORKER_API_KEY'], comfy, state,
                   input_dir, output_dir, workflow_dir, manifest,
                   project=os.getenv('GCP_PROJECT', 'novvy-dev'),
                   impersonate=os.getenv('GCS_IMPERSONATE_SERVICE_ACCOUNT', ''),
                   auth_mode=os.getenv('GCS_AUTH_MODE', 'adc'),
                   gcloud_account=os.getenv('GCLOUD_ACCOUNT', ''))

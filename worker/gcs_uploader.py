import base64
import hashlib
import json
import subprocess
from fractions import Fraction
from workflows.parameters import validate_output
import google.auth
import google_crc32c
from google.auth import impersonated_credentials
from google.cloud import storage
from google.api_core.exceptions import PreconditionFailed


def validate_video(path):
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError('Missing video')
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                            '-of', 'json', str(path)], capture_output=True, text=True, timeout=30)
    data = json.loads(probe.stdout) if probe.returncode == 0 else {}
    if (not any(s.get('codec_type') == 'video' for s in data.get('streams', [])) or
            float(data.get('format', {}).get('duration', 0)) <= 0 or
            'mp4' not in data.get('format', {}).get('format_name', '')):
        raise ValueError('Invalid MP4')
    video = next(s for s in data['streams'] if s.get('codec_type') == 'video')
    if not any(s.get('codec_type') == 'audio' for s in data['streams']):
        raise ValueError('Missing native audio')
    return {'width': int(video['width']), 'height': int(video['height']),
            'frame_count': int(video['nb_frames']), 'fps': float(Fraction(video['avg_frame_rate'])),
            'duration_seconds': float(data['format']['duration'])}


class Uploader:
    def __init__(self, settings):
        self.settings = settings
        self.client = None

    def upload(self, path, task, check=lambda: None):
        if self.client is None:
            if self.settings.auth_mode == 'gcloud':
                from worker.credentials import GcloudImpersonatedCredentials
                credentials = GcloudImpersonatedCredentials(self.settings.project,
                    self.settings.gcloud_account, self.settings.impersonate)
            elif self.settings.auth_mode == 'adc':
                credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
                if self.settings.impersonate:
                    credentials = impersonated_credentials.Credentials(credentials,
                        self.settings.impersonate, ['https://www.googleapis.com/auth/devstorage.read_write'], lifetime=3600)
            else:
                raise ValueError('GCS_AUTH_MODE must be adc or gcloud')
            self.client = storage.Client(project=self.settings.project, credentials=credentials)
        checksum = google_crc32c.Checksum()
        with path.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                check()
                checksum.update(chunk)
        expected_crc = base64.b64encode(checksum.digest()).decode()
        output = validate_video(path)
        validate_output(output, task['request']['resolution'], task['request']['ratio'], task['request']['duration'])
        metadata = {'output_spec': json.dumps(output, sort_keys=True), 'task_id': task['task_id'],
                    'lease_hash': hashlib.sha256(task['lease_token'].encode()).hexdigest(),
                    'workflow_revision': task['workflow_revision']}
        blob = self.client.bucket(task['gcs_bucket']).blob(task['gcs_object'])
        blob.metadata = metadata
        check()
        try:
            blob.upload_from_filename(str(path), content_type='video/mp4', if_generation_match=0,
                                      checksum='crc32c', timeout=20, retry=None)
        except PreconditionFailed:
            pass  # Lost upload response: verify the existing object rather than overwrite.
        blob.reload(timeout=20, retry=None)
        if (blob.size != path.stat().st_size or blob.crc32c != expected_crc or
                blob.content_type != 'video/mp4' or any((blob.metadata or {}).get(k) != v for k, v in metadata.items())):
            raise ValueError('Existing output does not match this task and lease')
        return {'generation': str(blob.generation), 'checksum': expected_crc}

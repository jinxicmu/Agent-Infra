import base64
import json
import subprocess
from fractions import Fraction

import google_crc32c
import requests

from workflows.parameters import validate_output


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
    """Uploads only through a short-lived, task-bound URL issued by Cloud Run."""
    def __init__(self, cloud):
        self.cloud = cloud

    def upload(self, path, task, check=lambda: None):
        checksum = google_crc32c.Checksum()
        with path.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                check()
                checksum.update(chunk)
        output = validate_video(path)
        validate_output(output, task['request']['resolution'], task['request']['ratio'], task['request']['duration'])
        authorization = self.cloud.upload_url(task, output, path.stat().st_size)
        check()
        with path.open('rb') as stream:
            response = requests.put(authorization['upload_url'], data=stream,
                                    headers=authorization['headers'], timeout=(5, 120), allow_redirects=False)
        # A retry after a lost response reaches the create-only precondition. The complete
        # endpoint independently verifies the stored object before publishing it.
        if response.status_code not in (200, 201, 412):
            response.raise_for_status()
        return {'checksum': base64.b64encode(checksum.digest()).decode()}

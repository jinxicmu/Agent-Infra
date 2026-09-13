import base64
from unittest.mock import Mock

import google_crc32c
from worker.gcs_uploader import Uploader


def test_signed_put_binds_local_media_contract(tmp_path, monkeypatch):
    output = {'width': 1344, 'height': 768, 'fps': 24, 'frame_count': 124, 'duration_seconds': 5.167}
    monkeypatch.setattr('worker.gcs_uploader.validate_video', lambda path: output)
    path = tmp_path / 'video.mp4'
    path.write_bytes(b'example-bytes')
    cloud = Mock()
    cloud.upload_url.return_value = {
        'upload_url': 'https://storage.example/upload',
        'headers': {'Content-Type': 'video/mp4', 'content-length': str(path.stat().st_size)},
    }
    monkeypatch.setattr('worker.gcs_uploader.requests.put', lambda *args, **kwargs: Mock(status_code=200))
    task = {'task_id': 'gen_a', 'lease_token': 'secret', 'workflow_revision': 'rev',
            'request': {'resolution': '768P', 'ratio': '16:9', 'duration': 5}}

    artifact = Uploader(cloud).upload(path, task)

    cloud.upload_url.assert_called_once_with(task, output, path.stat().st_size)
    assert artifact['checksum'] == base64.b64encode(
        google_crc32c.Checksum(path.read_bytes()).digest()).decode()


def test_create_only_retry_allows_verifier_to_decide(tmp_path, monkeypatch):
    monkeypatch.setattr('worker.gcs_uploader.validate_video', lambda path: {
        'width': 1344, 'height': 768, 'fps': 24, 'frame_count': 124, 'duration_seconds': 5.167})
    path = tmp_path / 'video.mp4'
    path.write_bytes(b'example-bytes')
    cloud = Mock()
    cloud.upload_url.return_value = {'upload_url': 'https://storage.example/upload', 'headers': {}}
    monkeypatch.setattr('worker.gcs_uploader.requests.put', lambda *args, **kwargs: Mock(status_code=412))
    task = {'request': {'resolution': '768P', 'ratio': '16:9', 'duration': 5}}
    assert Uploader(cloud).upload(path, task)['checksum']

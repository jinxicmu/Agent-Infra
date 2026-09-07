import base64
import hashlib
from types import SimpleNamespace
from unittest.mock import Mock
import google_crc32c
from google.api_core.exceptions import PreconditionFailed
import pytest
from worker.gcs_uploader import Uploader
from cloudrun.result_verifier import ResultVerifier
from cloudrun.errors import ApiError


def test_create_only_upload_retry_verifies_crc_and_metadata(tmp_path):
    path = tmp_path/'video.mp4'
    path.write_bytes(b'example-bytes')
    task = {'task_id':'gen_a', 'lease_token':'secret', 'workflow_revision':'rev',
            'gcs_bucket':'bucket', 'gcs_object':'generated_video_dir/gen_a.mp4'}
    blob = Mock(size=path.stat().st_size, content_type='video/mp4', generation=123)
    blob.crc32c = base64.b64encode(google_crc32c.Checksum(path.read_bytes()).digest()).decode()
    blob.upload_from_filename.side_effect = PreconditionFailed('already exists')
    client = Mock()
    client.bucket.return_value.blob.return_value = blob
    uploader = Uploader(SimpleNamespace())
    uploader.client = client
    assert uploader.upload(path, task)['generation'] == '123'
    assert blob.upload_from_filename.call_args.kwargs['if_generation_match'] == 0
    blob.crc32c = 'wrong'
    with pytest.raises(ValueError):
        uploader.upload(path, task)


def test_cloud_rejects_foreign_artifact():
    client = Mock()
    blob = Mock(size=123, content_type='video/mp4', crc32c='AAAAAA==', generation=123,
                metadata={'task_id':'another-task'})
    client.bucket.return_value.blob.return_value = blob
    with pytest.raises(ApiError) as error:
        ResultVerifier(client).verify({'task_id':'gen_a','lease_token':'secret','workflow_revision':'rev',
            'gcs_bucket':'bucket','gcs_object':'generated_video_dir/gen_a.mp4'})
    assert error.value.code == 'RESULT_VERIFICATION_FAILED'

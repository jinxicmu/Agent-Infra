import hashlib
import json
from workflows.parameters import validate_output
from google.api_core.exceptions import NotFound
from cloudrun.errors import ApiError


class ResultVerifier:
    def __init__(self, storage_client):
        self.client = storage_client

    def verify(self, task):
        blob = self.client.bucket(task['gcs_bucket']).blob(task['gcs_object'])
        try:
            blob.reload(timeout=20)
        except NotFound:
            raise ApiError(409, 'RESULT_VERIFICATION_FAILED') from None
        metadata = blob.metadata or {}
        expected = {'task_id': task['task_id'],
                    'lease_hash': hashlib.sha256(task['lease_token'].encode()).hexdigest(),
                    'workflow_revision': task['workflow_revision']}
        if (not blob.size or blob.content_type != 'video/mp4' or not blob.crc32c or
                any(metadata.get(key) != value for key, value in expected.items())):
            raise ApiError(409, 'RESULT_VERIFICATION_FAILED')
        result = {}
        if task.get('parameter_version') == 1:
            try:
                output = json.loads(metadata['output_spec'])
                req = task['request']
                validate_output(output, req['resolution'], req['ratio'], req['duration'])
            except (KeyError, ValueError, TypeError, OverflowError):
                raise ApiError(409, 'RESULT_VERIFICATION_FAILED') from None
            result['output'] = {key: output[key] for key in
                                ('width', 'height', 'fps', 'frame_count', 'duration_seconds')}
        return {**result, 'gcs_generation': str(blob.generation),
                'checksum': {'algorithm': 'crc32c', 'value': blob.crc32c}, 'output_bytes': blob.size}

"""Create-only GCS upload URLs bound to an active worker lease."""
import hashlib
import json
from datetime import timedelta

import google.auth
from google.auth.transport.requests import Request


class SignedUploadIssuer:
    def __init__(self, storage_client, credentials=None):
        self.client = storage_client
        self.credentials = credentials

    def issue(self, task, output, content_length):
        """Sign one exact object, metadata set, content type, and byte length for PUT."""
        credentials = self.credentials
        if credentials is None:
            credentials, _ = google.auth.default(
                scopes=['https://www.googleapis.com/auth/cloud-platform'])
        credentials.refresh(Request())
        metadata = {
            'output_spec': json.dumps(output, sort_keys=True, separators=(',', ':')),
            'task_id': task['task_id'],
            'lease_hash': hashlib.sha256(task['lease_token'].encode()).hexdigest(),
            'workflow_revision': task['workflow_revision'],
        }
        headers = {
            'content-length': str(content_length),
            **{f'x-goog-meta-{key}': value for key, value in metadata.items()},
        }
        blob = self.client.bucket(task['gcs_bucket']).blob(task['gcs_object'])
        url = blob.generate_signed_url(
            version='v4', expiration=timedelta(minutes=15), method='PUT',
            content_type='video/mp4', headers=headers,
            query_parameters={'ifGenerationMatch': '0'},
            service_account_email=credentials.service_account_email,
            access_token=credentials.token,
        )
        return {'upload_url': url, 'headers': {'Content-Type': 'video/mp4', **headers},
                'expires_in_seconds': 900}

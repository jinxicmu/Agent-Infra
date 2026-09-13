from unittest.mock import Mock

from cloudrun.signed_upload import SignedUploadIssuer


def test_issuer_binds_exact_media_and_create_only_condition():
    credentials = Mock(service_account_email='runtime@example.iam.gserviceaccount.com', token='token')
    blob = Mock()
    client = Mock()
    client.bucket.return_value.blob.return_value = blob
    task = {'task_id': 'gen_' + 'a' * 32, 'lease_token': 'secret', 'workflow_revision': 'revision',
            'gcs_bucket': 'bucket', 'gcs_object': 'generated_video_dir/output.mp4'}
    output = {'width': 1344, 'height': 768, 'fps': 24.0, 'frame_count': 124, 'duration_seconds': 5.167}

    result = SignedUploadIssuer(client, credentials).issue(task, output, 123)

    credentials.refresh.assert_called_once()
    kwargs = blob.generate_signed_url.call_args.kwargs
    assert kwargs['method'] == 'PUT'
    assert kwargs['content_type'] == 'video/mp4'
    assert kwargs['query_parameters'] == {'ifGenerationMatch': '0'}
    assert kwargs['headers']['content-length'] == '123'
    assert kwargs['headers']['x-goog-meta-task_id'] == task['task_id']
    assert result['headers']['Content-Type'] == 'video/mp4'

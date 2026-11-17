import pytest
from unittest.mock import Mock
from fastapi.testclient import TestClient
from cloudrun.main import create_app


@pytest.mark.parametrize('with_last_frame', [False, True])
def test_api_create_claim_complete_and_repeat(store, settings, request_body, with_last_frame):
    if not with_last_frame:
        request_body['content'] = request_body['content'][:2]
    verifier = Mock()
    verifier.verify.return_value = {'gcs_generation': '123', 'checksum': {'algorithm': 'crc32c', 'value': 'AAAAAA=='}}
    with TestClient(create_app(settings, store, verifier)) as api:
        client = {'Authorization': 'Bearer ' + settings.clients['client-a']}
        worker = {'Authorization': 'Bearer ' + settings.workers['worker-a']}
        response = api.post('/v2/video_generation', json=request_body, headers=client)
        assert response.status_code == 200, response.text
        task_id = response.json()['task_id']
        claim = api.post('/internal/workers/claim', json={'worker_session_id': 'session', 'workflow_revision': settings.revision}, headers=worker)
        assert claim.status_code == 200, claim.text
        task = claim.json()
        assert 'server_time' in task
        body = {k: task[k] for k in ('worker_session_id', 'workflow_revision', 'lease_token')}
        for _ in range(2):
            result = api.post(f'/internal/tasks/{task_id}/complete', json=body, headers=worker)
            assert result.status_code == 200, result.text
        verifier.verify.assert_called_once()
        public = api.get('/v2/query/video_generation', params={'task_id': task_id}, headers=client).json()['task']
        assert public['status'] == 'succeeded'
        assert public['workflow_type'] == ('fl2v' if with_last_frame else 'i2v_first')
        assert public['usage']['input_image_count'] == (2 if with_last_frame else 1)
        assert public['content']['gcs_generation'] == '123'
        assert 'lease_token' not in str(public)
        denied = api.get('/v2/query/video_generation', params={'task_id': task_id}, headers={'Authorization': 'Bearer ' + settings.clients['client-b']})
        assert denied.status_code == 404


def test_worker_can_request_upload_url_only_for_its_live_lease(store, settings, request_body):
    issuer = Mock()
    issuer.issue.return_value = {'upload_url': 'https://storage.example/upload', 'headers': {}, 'expires_in_seconds': 900}
    with TestClient(create_app(settings, store, Mock())) as api:
        api.app.state.upload_issuer = issuer
        client = {'Authorization': 'Bearer ' + settings.clients['client-a']}
        worker = {'Authorization': 'Bearer ' + settings.workers['worker-a']}
        task_id = api.post('/v2/video_generation', json=request_body, headers=client).json()['task_id']
        task = api.post('/internal/workers/claim', json={
            'worker_session_id': 'session', 'workflow_revision': settings.revision}, headers=worker).json()
        body = {key: task[key] for key in ('worker_session_id', 'workflow_revision', 'lease_token')} | {
            'content_length': 123,
            'output': {'width': 1344, 'height': 768, 'fps': 24, 'frame_count': 124, 'duration_seconds': 124 / 24},
        }
        response = api.post(f'/internal/tasks/{task_id}/upload-url', json=body, headers=worker)
        assert response.status_code == 200, response.text
        issuer.issue.assert_called_once()
        assert store.get(task_id)['status'] == 'uploading'
        body['lease_token'] = 'wrong-token-that-is-long-enough'
        assert api.post(f'/internal/tasks/{task_id}/upload-url', json=body, headers=worker).status_code == 409


def test_auth_and_validation(store, settings, request_body):
    with TestClient(create_app(settings, store, Mock())) as api:
        assert api.post('/v2/video_generation', json=request_body).status_code == 401
        headers = {'Authorization': 'Bearer ' + settings.clients['client-a']}
        assert api.post('/internal/workers/claim', headers=headers,
                        json={'worker_session_id':'a', 'workflow_revision':settings.revision}).status_code == 403
        response = api.post('/v2/video_generation', headers=headers, json={**request_body, 'mode': 'bad'})
        assert response.json()['error']['code'] == 'INVALID_MODE'
        assert api.post('/v2/video_generation', headers=headers, content=b'x'*65537).status_code == 413
        assert api.post('/internal/maintenance/expire-leases', headers=headers).status_code == 401


def test_public_health_alias_does_not_require_database(settings):
    with TestClient(create_app(settings, Mock(), Mock())) as api:
        assert api.get('/health').json() == {'status': 'ok'}
        assert api.get('/healthz').json() == {'status': 'ok'}


def test_admission_pause_keeps_health_and_workers_available(settings, request_body):
    settings.accept_submissions = False
    store = Mock()
    store.claim.return_value = None
    with TestClient(create_app(settings, store, Mock())) as api:
        response = api.post('/v2/video_generation', json=request_body,
                            headers={'Authorization': 'Bearer ' + settings.clients['client-a']})
        assert response.status_code == 503
        assert response.json()['error']['code'] == 'SERVICE_MAINTENANCE'
        store.create.assert_not_called()
        assert api.get('/health').status_code == 200
        response = api.post('/internal/workers/claim',
                            json={'worker_session_id':'session','workflow_revision':settings.revision},
                            headers={'Authorization': 'Bearer ' + settings.workers['worker-a']})
        assert response.status_code == 204
        store.claim.assert_called_once()


def test_cancel_queued_running_and_finished(store, settings, request_body):
    verifier = Mock()
    verifier.verify.return_value = {'gcs_generation': '1', 'checksum': {'algorithm': 'crc32c', 'value': 'AAAAAA=='}}
    with TestClient(create_app(settings, store, verifier)) as api:
        client = {'Authorization': 'Bearer ' + settings.clients['client-a']}
        other = {'Authorization': 'Bearer ' + settings.clients['client-b']}
        worker = {'Authorization': 'Bearer ' + settings.workers['worker-a']}
        submit = lambda: api.post('/v2/video_generation', json=request_body, headers=client).json()['task_id']
        cancel = lambda tid, h=client: api.post('/v2/cancel/video_generation', params={'task_id': tid}, headers=h)
        claim = lambda: api.post('/internal/workers/claim', json={'worker_session_id': 'session', 'workflow_revision': settings.revision}, headers=worker)
        running, queued, later = submit(), submit(), submit()

        # Queued: cancelled before any worker sees it; repeating is harmless; other clients cannot see it.
        assert cancel(queued, other).status_code == 404
        assert cancel(queued).json() == {'task_id': queued, 'status': 'cancelled', 'cancelled': True}
        assert cancel(queued).json()['cancelled'] is True
        public = api.get('/v2/query/video_generation', params={'task_id': queued}, headers=client).json()['task']
        assert public['status'] == 'cancelled' and public['error']['code'] == 'CANCELLED_BY_CLIENT'

        # Running: the worker is fenced off on its next heartbeat and can take the next task at once.
        task = claim().json()
        assert task['task_id'] == running
        proof = {k: task[k] for k in ('worker_session_id', 'workflow_revision', 'lease_token')}
        assert api.post(f'/internal/tasks/{running}/heartbeat', json=proof | {'phase': 'running'}, headers=worker).status_code == 200
        assert cancel(running).json()['cancelled'] is True
        beat = api.post(f'/internal/tasks/{running}/heartbeat', json=proof | {'phase': 'running'}, headers=worker)
        assert beat.status_code == 409 and beat.json()['error']['code'] == 'TASK_ALREADY_TERMINAL'
        assert api.post(f'/internal/tasks/{running}/complete', json=proof, headers=worker).status_code == 409
        verifier.verify.assert_not_called()
        nxt = claim().json()
        assert nxt['task_id'] == later  # the cancelled queued task was skipped

        # Finished: left alone.
        proof = {k: nxt[k] for k in ('worker_session_id', 'workflow_revision', 'lease_token')}
        assert api.post(f'/internal/tasks/{later}/complete', json=proof, headers=worker).status_code == 200
        assert cancel(later).json() == {'task_id': later, 'status': 'succeeded', 'cancelled': False}
        assert cancel('gen_' + '0' * 32).status_code == 404

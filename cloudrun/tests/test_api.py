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

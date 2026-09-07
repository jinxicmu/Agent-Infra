import pytest
from cloudrun.schemas import CreateVideoRequest
from cloudrun.validation import validate
from cloudrun.errors import ApiError
from workflows.parameters import canvas


def reference_request(count=1, **kwargs):
    return dict(model='MiniMax-H3', mode='realtime', content=[
        {'type': 'text', 'text': '让 <Picture 1> 中的医生开口说话。'},
        *[{'type': 'image_url', 'role': 'reference_image',
           'image_url': f'https://example.com/{i}.png'} for i in range(count)]], **kwargs)


def test_reference_defaults_and_explicit_parameters():
    implicit = validate(CreateVideoRequest(**reference_request()))
    explicit = validate(CreateVideoRequest(**reference_request(
        workflow_type='ref2va', resolution='544P', ratio='16:9', duration=5)))
    assert implicit == explicit
    assert canvas(implicit['resolution'], implicit['ratio']) == (960, 544)
    custom = validate(CreateVideoRequest(**reference_request(
        resolution='720P', ratio='9:16', duration=7)))
    assert (custom['resolution'], custom['ratio'], custom['duration']) == ('720P', '9:16', 7)


@pytest.mark.parametrize('count', [0, 10])
def test_reference_count_limits(count):
    with pytest.raises(ApiError) as error:
        validate(CreateVideoRequest(**reference_request(count, workflow_type='ref2va')))
    assert error.value.code == 'UNSUPPORTED_WORKFLOW_COMBINATION'


def test_reference_and_boundary_frames_cannot_mix():
    body = reference_request()
    body['content'].append({'type': 'image_url', 'role': 'first_frame', 'image_url': 'https://example.com/a'})
    with pytest.raises(ApiError):
        validate(CreateVideoRequest(**body))
    with pytest.raises(ApiError):
        validate(CreateVideoRequest(**reference_request(workflow_type='fl2v')))


def test_reference_queue_assignment_and_idempotency(store):
    request = validate(CreateVideoRequest(**reference_request(9)))
    task = store.create(request, 'client-a', 'ref-key')
    assert task['workflow_type'] == 'ref2va'
    assert store.create(request, 'client-a', 'ref-key')['task_id'] == task['task_id']
    claim = store.claim('worker-a', 'session', store.s.revision)
    assert claim['task_id'] == task['task_id']
    assert claim['request']['content'] == request['content']
    assert store.claim('worker-b', 'other-session', store.s.revision) is None


def test_reference_http_contract(store, settings):
    from fastapi.testclient import TestClient
    from unittest.mock import Mock
    from cloudrun.main import create_app
    with TestClient(create_app(settings, store, Mock())) as api:
        headers = {'Authorization': 'Bearer ' + settings.clients['client-a']}
        response = api.post('/v2/video_generation', json=reference_request(2), headers=headers)
        assert response.status_code == 200
        task = api.get('/v2/query/video_generation', params={'task_id': response.json()['task_id']}, headers=headers).json()['task']
        assert task['workflow_type'] == 'ref2va'
        assert task['resolution'] == '544P'
        assert task['usage']['input_image_count'] == 2

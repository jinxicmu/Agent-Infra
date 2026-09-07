import pytest
from cloudrun.errors import ApiError
from cloudrun.schemas import CreateVideoRequest
from cloudrun.validation import validate


def test_fixed_source_canvas_is_explicit_in_api(request_body):
    assert validate(CreateVideoRequest(**request_body))['ratio'] == '16:9'
    with pytest.raises(ApiError) as error:
        validate(CreateVideoRequest(**{**request_body, 'ratio': 'adaptive'}))
    assert error.value.code == 'INVALID_RATIO_FOR_WORKFLOW'


@pytest.mark.parametrize('roles', [[], ['last_frame'], ['first_frame', 'first_frame'],
                                  ['first_frame', 'last_frame', 'last_frame'], [None]])
def test_reject_unsupported_frame_combinations(request_body, roles):
    content = [request_body['content'][0]] + [
        {'type': 'image_url', 'role': role, 'image_url': 'https://example.com/a.png'}
        for role in roles]
    with pytest.raises(ApiError) as error:
        validate(CreateVideoRequest(**{**request_body, 'content': content}))
    assert error.value.code == 'UNSUPPORTED_WORKFLOW_COMBINATION'


def test_first_frame_only_is_accepted(request_body):
    request_body['content'] = request_body['content'][:2]
    assert len(validate(CreateVideoRequest(**request_body))['content']) == 2

from cloudrun.errors import ApiError
from workflows.parameters import validate_parameters, ParameterError


def validate(req):
    if req.model != 'MiniMax-H3':
        raise ApiError(400, 'UNSUPPORTED_MODEL')
    if req.callback_url is not None:
        raise ApiError(400, 'UNSUPPORTED_PARAMETER')
    text = [c for c in req.content if c.type == 'text']
    images = [c for c in req.content if c.type == 'image_url']
    if len(text) != 1 or not (text[0].text or '').strip():
        raise ApiError(400, 'INVALID_REQUEST', 'Exactly one nonempty text item is required')
    if any(not c.image_url for c in images):
        raise ApiError(400, 'INVALID_REQUEST', 'Image URL is required')
    roles = [c.role for c in images]
    if roles.count('first_frame') != 1 or roles.count('last_frame') > 1 or any(
            role not in {'first_frame', 'last_frame'} for role in roles):
        raise ApiError(400, 'UNSUPPORTED_WORKFLOW_COMBINATION')
    try:
        validate_parameters(req.resolution, req.ratio, req.duration)
    except ParameterError as exc:
        raise ApiError(400, exc.code) from None
    return req.model_dump(exclude_none=True)

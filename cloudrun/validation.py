from cloudrun.errors import ApiError
from workflows.parameters import validate_parameters, ParameterError, POLICY


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
    is_reference = 'reference_image' in roles or req.workflow_type == 'ref2va'
    if is_reference:
        if not 1 <= len(images) <= 9 or any(role != 'reference_image' for role in roles):
            raise ApiError(400, 'UNSUPPORTED_WORKFLOW_COMBINATION')
        workflow_type = 'ref2va'
    elif roles.count('first_frame') != 1 or roles.count('last_frame') > 1 or any(
            role not in {'first_frame', 'last_frame'} for role in roles):
        raise ApiError(400, 'UNSUPPORTED_WORKFLOW_COMBINATION')
    else:
        workflow_type = 'fl2v' if 'last_frame' in roles else 'i2v_first'
    if req.workflow_type is not None and req.workflow_type != workflow_type:
        raise ApiError(400, 'UNSUPPORTED_WORKFLOW_COMBINATION')
    normalized = req.model_dump(exclude_none=True)
    # Resolve omitted defaults by workflow; explicit client parameters always win.
    if workflow_type == 'ref2va':
        for name, value in POLICY['ref2va_defaults'].items():
            if name not in req.model_fields_set:
                normalized[name] = value
        normalized['workflow_type'] = workflow_type
    else:
        # Preserve existing idempotency fingerprints for legacy requests.
        normalized.pop('workflow_type', None)
    try:
        validate_parameters(normalized['resolution'], normalized['ratio'], normalized['duration'])
    except ParameterError as exc:
        raise ApiError(400, exc.code) from None
    return normalized

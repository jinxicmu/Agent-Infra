import hmac
from fastapi import Request
from cloudrun.errors import ApiError


def identity(request: Request, role):
    value = request.headers.get('authorization', '')
    if not value.startswith('Bearer '):
        raise ApiError(401, 'AUTH_FAILED')
    token = value[7:]
    settings = request.app.state.settings
    allowed = settings.clients if role == 'client' else settings.workers
    for name, secret in allowed.items():
        if hmac.compare_digest(token.encode(), secret.encode()):
            return name
    other = settings.workers if role == 'client' else settings.clients
    if any(hmac.compare_digest(token.encode(), secret.encode()) for secret in other.values()):
        raise ApiError(403, 'FORBIDDEN')
    raise ApiError(401, 'AUTH_FAILED')


def client_identity(request: Request):
    return identity(request, 'client')


def worker_identity(request: Request):
    return identity(request, 'worker')

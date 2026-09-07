from fastapi import APIRouter, Request
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from cloudrun.errors import ApiError

router = APIRouter(prefix='/internal/maintenance')


@router.post('/expire-leases')
def expire(request: Request):
    settings = request.app.state.settings
    value = request.headers.get('authorization', '')
    if not value.startswith('Bearer ') or not settings.scheduler_audience or not settings.scheduler_email:
        raise ApiError(401, 'AUTH_FAILED')
    try:
        claims = id_token.verify_oauth2_token(value[7:], GoogleRequest(), settings.scheduler_audience)
    except ValueError:
        raise ApiError(401, 'AUTH_FAILED') from None
    if claims.get('email') != settings.scheduler_email or claims.get('email_verified') is not True:
        raise ApiError(403, 'FORBIDDEN')
    return {'expired': request.app.state.store.sweep()}

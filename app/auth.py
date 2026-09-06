from fastapi import Header
from app import config
from app.errors import ApiError


def require_api_key(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise ApiError(401, "AUTH_FAILED", "Missing or malformed Authorization header")
    token = authorization[len("Bearer "):]
    if token != config.AI_STUDIO_API_KEY:
        raise ApiError(401, "AUTH_FAILED", "Invalid API key")

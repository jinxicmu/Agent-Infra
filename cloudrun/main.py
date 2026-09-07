import logging
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from google.api_core.exceptions import GoogleAPICallError, RetryError
from cloudrun.config import Settings
from cloudrun.errors import ApiError
from cloudrun import public_api, worker_api, maintenance


def error_response(request, status, code, message):
    headers = {'Retry-After': '5'} if status in (429, 503) else {}
    return JSONResponse(status_code=status, headers=headers, content={
        'type': 'error', 'error': {'type': 'bad_request_error' if status < 500 else 'internal_error',
                                 'code': code, 'message': message, 'http_code': str(status)},
        'request_id': getattr(request.state, 'request_id', 'req_unknown')})


def create_app(settings=None, store=None, verifier=None):
    @asynccontextmanager
    async def lifespan(app):
        if app.state.store is None:
            from google.cloud import firestore, storage
            from cloudrun.task_store import TaskStore
            from cloudrun.result_verifier import ResultVerifier
            cfg = settings or Settings.from_env()
            app.state.settings = cfg
            app.state.store = TaskStore(firestore.Client(project=cfg.project, database=cfg.database), cfg)
            app.state.verifier = ResultVerifier(storage.Client(project=cfg.project))
        yield
    app = FastAPI(title='AI Studio Cloud API', lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings, app.state.store, app.state.verifier = settings, store, verifier

    @app.middleware('http')
    async def context(request: Request, call_next):
        request.state.request_id = 'req_' + uuid.uuid4().hex
        # Bound chunked requests too. Starlette replays the cached body downstream.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                return error_response(request, 413, 'INVALID_REQUEST', 'Request exceeds 64 KiB')
        request._body = bytes(body)
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.request_id
        return response

    @app.exception_handler(ApiError)
    async def api_error(request, exc):
        return error_response(request, exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        first = exc.errors()[0]
        loc = first.get('loc', ())
        code = next((code for field, code in [('mode', 'INVALID_MODE'), ('type', 'UNSUPPORTED_CONTENT_TYPE'),
                    ('role', 'UNSUPPORTED_CONTENT_ROLE')] if field in loc), 'INVALID_REQUEST')
        if first.get('type') == 'extra_forbidden':
            code = 'UNSUPPORTED_PARAMETER'
        return error_response(request, 400, code, 'Invalid request fields')

    @app.exception_handler(GoogleAPICallError)
    @app.exception_handler(RetryError)
    async def unavailable(request, exc):
        logging.getLogger(__name__).warning('Cloud dependency failure: %s', type(exc).__name__)
        return error_response(request, 503, 'QUEUE_UNAVAILABLE', 'Cloud dependency temporarily unavailable')

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        logging.getLogger(__name__).error('Unhandled request error: %s', type(exc).__name__)
        return error_response(request, 500, 'INTERNAL_ERROR', 'Internal service error')

    app.include_router(public_api.router)
    app.include_router(worker_api.router)
    app.include_router(maintenance.router)
    return app


app = create_app()

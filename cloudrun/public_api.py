import re
from fastapi import APIRouter, Depends, Header, Request
from cloudrun.auth import client_identity
from cloudrun.errors import ApiError
from cloudrun.errors import ApiError
from cloudrun.schemas import CreateVideoRequest
from cloudrun.validation import validate

router = APIRouter()


@router.get('/health')
@router.get('/healthz', include_in_schema=False)
def health():
    return {'status': 'ok'}


@router.post('/v2/video_generation')
def create(req: CreateVideoRequest, request: Request, client=Depends(client_identity),
           idempotency_key: str | None = Header(default=None, max_length=256)):
    if not request.app.state.settings.accept_submissions:
        raise ApiError(503, 'SERVICE_MAINTENANCE', 'Task submissions are temporarily paused for a coordinated rollout')
    task = request.app.state.store.create(validate(req), client, idempotency_key)
    return {'task_id': task['task_id'], 'status': 'accepted', 'mode': task['mode']}


@router.get('/v2/query/video_generation')
def query(task_id: str, request: Request, client=Depends(client_identity)):
    if not re.fullmatch(r'gen_[a-f0-9]{32}', task_id):
        raise ApiError(404, 'TASK_NOT_FOUND')
    task = request.app.state.store.get(task_id)
    if task['client_id'] != client:
        raise ApiError(404, 'TASK_NOT_FOUND')
    status = {'leased': 'queued', 'uploading': 'running'}.get(task['status'], task['status'])
    content = None
    if status == 'succeeded':
        content = {'gcs_uri': f"gs://{task['gcs_bucket']}/{task['gcs_object']}",
                   'bucket': task['gcs_bucket'], 'object': task['gcs_object'],
                   'gcs_generation': task['gcs_generation'], 'checksum': task['checksum']}
    req = task['request']
    return {'task': {
        'id': task_id, 'model': task['model'], 'status': status,
        'created_at': int(task['created_at'].timestamp()),
        'updated_at': int(task['updated_at'].timestamp()),
        'content': content, 'resolution': req['resolution'], 'duration': req['duration'],
        'ratio': req['ratio'], 'mode': task['mode'], 'workflow_type': task['workflow_type'],
        'scheduler_state': task['status'], 'task_type': 'generation', 'modality': 'video',
        'usage': {'input_image_count': sum(c['type'] == 'image_url' for c in req['content']), 'output_seconds': req['duration']},
        'metrics': task.get('metrics'), 'error': task.get('error'),
        'output': task.get('output'),
    }}

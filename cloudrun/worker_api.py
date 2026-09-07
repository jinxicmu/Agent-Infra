from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request, Response
from cloudrun.auth import worker_identity
from cloudrun.schemas import ClaimRequest, LeaseRequest, HeartbeatRequest, RecoverRequest, FailureRequest

router = APIRouter(prefix='/internal')


def assignment(task):
    fields = ('task_id', 'request', 'worker_id', 'worker_session_id', 'lease_token',
              'lease_deadline', 'execution_deadline', 'workflow_revision', 'workflow_type',
              'seed', 'comfy_prompt_id', 'status', 'gcs_bucket', 'gcs_object')
    return {**{key: task.get(key) for key in fields}, 'server_time': datetime.now(timezone.utc)}


@router.post('/workers/claim')
def claim(req: ClaimRequest, request: Request, worker=Depends(worker_identity)):
    task = request.app.state.store.claim(worker, req.worker_session_id, req.workflow_revision)
    return assignment(task) if task else Response(status_code=204)


@router.post('/workers/recover')
def recover(req: RecoverRequest, request: Request, worker=Depends(worker_identity)):
    return assignment(request.app.state.store.recover(worker, req.model_dump()))


@router.post('/tasks/{task_id}/heartbeat')
def heartbeat(task_id: str, req: HeartbeatRequest, request: Request, worker=Depends(worker_identity)):
    return assignment(request.app.state.store.mutate(task_id, worker, req.model_dump(), 'heartbeat'))


@router.post('/tasks/{task_id}/complete')
def complete(task_id: str, req: LeaseRequest, request: Request, worker=Depends(worker_identity)):
    store = request.app.state.store
    # Check ownership before touching GCS; the commit checks it again afterwards.
    task = store.mutate(task_id, worker, req.model_dump(), 'check')
    if task['status'] == 'succeeded':
        return {'task_id': task_id, 'status': 'succeeded'}
    result = request.app.state.verifier.verify(task)
    finished = store.mutate(task_id, worker, req.model_dump(), 'complete', result)
    return {'task_id': task_id, 'status': finished['status']}


@router.post('/tasks/{task_id}/fail')
def fail(task_id: str, req: FailureRequest, request: Request, worker=Depends(worker_identity)):
    finished = request.app.state.store.mutate(task_id, worker, req.model_dump(), 'fail')
    return {'task_id': task_id, 'status': finished['status']}

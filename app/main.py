import time
import uuid

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import comfy_client, config, dispatcher
from app.auth import require_api_key
from app.errors import ApiError
from app.job_store import job_store
from app.scheduler import scheduler
from app.schemas import CreateVideoRequest, CreateVideoResponse, QueryResponse, Task, TaskContent, TaskUsage
from app.workflow_router import infer_workflow_type, resolve_workflow, validate_duration, validate_ratio, validate_resolution

app = FastAPI(title="AI Studio MiniMax H3 API")

_PUBLIC_STATUS = {
    "accepted": "queued",
    "queued": "queued",
    "prefetched": "queued",
    "running": "running",
    "uploading": "running",
    "succeeded": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
}


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    detail = dict(exc.detail)
    detail["request_id"] = getattr(request.state, "request_id", "req_unknown")
    return JSONResponse(status_code=exc.status_code, content=detail)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    loc = first.get("loc", ())
    code = "INVALID_MODE" if "mode" in loc else "INVALID_REQUEST"
    message = first.get("msg", "Invalid request body")
    if loc:
        message = f"{'.'.join(str(p) for p in loc)}: {message}"
    return JSONResponse(status_code=400, content={
        "type": "error",
        "error": {"type": "bad_request_error", "message": message, "http_code": "400", "code": code},
        "request_id": getattr(request.state, "request_id", "req_unknown"),
    })


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request.state.request_id = f"req_{uuid.uuid4().hex[:24]}"
    return await call_next(request)


@app.on_event("startup")
def on_startup():
    dispatcher.start()


@app.get("/healthz")
def healthz():
    comfy_ok = comfy_client.is_healthy()
    return {"status": "ok" if comfy_ok else "degraded", "comfyui_healthy": comfy_ok}


@app.post("/v2/video_generation", response_model=CreateVideoResponse, dependencies=[Depends(require_api_key)])
def create_video_generation(req: CreateVideoRequest):
    if req.model == "MiniMax-H3-Max":
        raise ApiError(400, "UNSUPPORTED_MODEL", "MiniMax-H3-Max is not installed/validated on this deployment")

    workflow_type = infer_workflow_type(req)
    resolve_workflow(req.model, workflow_type)
    validate_resolution(req.model, req.resolution)
    validate_duration(req.model, req.duration)
    validate_ratio(req.model, workflow_type, req.ratio)

    if req.callback_url is not None:
        raise ApiError(400, "UNSUPPORTED_PARAMETER", "callback_url is not implemented in this baseline")

    realtime_pending = scheduler.pending_count("realtime")
    batch_pending = scheduler.pending_count("batch")
    if req.mode == "realtime" and realtime_pending >= config.MAX_PENDING_REALTIME:
        raise ApiError(400, "QUEUE_FULL", "realtime queue is full")
    if req.mode == "batch" and batch_pending >= config.MAX_PENDING_BATCH:
        raise ApiError(400, "QUEUE_FULL", "batch queue is full")
    if realtime_pending + batch_pending >= config.MAX_TOTAL_PENDING:
        raise ApiError(400, "QUEUE_FULL", "total pending queue is full")

    task_id = f"gen_{uuid.uuid4().hex}"
    image_count = sum(1 for c in req.content if c.type == "image_url")

    job_store.create({
        "task_id": task_id,
        "model": req.model,
        "mode": req.mode,
        "workflow_type": workflow_type,
        "status": "accepted",
        "scheduler_state": "queued",
        "request": {
            "resolution": req.resolution,
            "duration": req.duration,
            "ratio": req.ratio,
            "mode": req.mode,
            "content": [c.model_dump() for c in req.content],
        },
        "comfy_prompt_id": None,
        "local_output_file": None,
        "gcs_uri": None,
        "gcs_bucket": None,
        "gcs_object": None,
        "error": None,
        "metadata": req.metadata or {},
        "usage": {"input_image_count": image_count, "output_seconds": req.duration},
    })
    scheduler.enqueue(task_id, req.mode)

    return CreateVideoResponse(task_id=task_id, status="accepted", mode=req.mode)


@app.get("/v2/query/video_generation", response_model=QueryResponse, dependencies=[Depends(require_api_key)])
def query_video_generation(task_id: str = Query(...)):
    job = job_store.get(task_id)
    if job is None:
        raise ApiError(404, "TASK_NOT_FOUND", f"No such task_id: {task_id}")

    content = None
    if job["status"] == "succeeded":
        content = TaskContent(gcs_uri=job["gcs_uri"], bucket=job["gcs_bucket"], object=job["gcs_object"])

    task = Task(
        id=job["task_id"],
        model=job["model"],
        status=_PUBLIC_STATUS.get(job["status"], job["status"]),
        created_at=job["created_at"],
        updated_at=job["updated_at"],
        content=content,
        resolution=job["request"]["resolution"],
        duration=job["request"]["duration"],
        ratio=job["request"]["ratio"],
        mode=job["mode"],
        workflow_type=job["workflow_type"],
        scheduler_state=job.get("scheduler_state"),
        usage=TaskUsage(**job["usage"]) if job.get("usage") else None,
        error=job.get("error"),
    )
    return QueryResponse(task=task)

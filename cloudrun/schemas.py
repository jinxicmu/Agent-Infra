from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict


class ContentItem(BaseModel):
    type: Literal["text", "image_url"]
    text: Optional[str] = None
    role: Optional[Literal["first_frame", "last_frame"]] = None
    image_url: Optional[str] = None


class CreateVideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    mode: Literal["realtime", "batch"]
    content: list[ContentItem] = Field(description="One text prompt and one first_frame image are required; last_frame image is optional.")
    resolution: str
    duration: int
    ratio: str
    callback_url: Optional[str] = None
    metadata: Optional[dict] = None


class CreateVideoResponse(BaseModel):
    task_id: str
    status: str = "accepted"
    mode: str


class TaskUsage(BaseModel):
    input_image_count: int
    output_seconds: int


class TaskMetrics(BaseModel):
    queue_time_ms: Optional[int] = None
    inference_time_ms: Optional[int] = None
    upload_time_ms: Optional[int] = None
    total_time_ms: Optional[int] = None


class TaskContent(BaseModel):
    gcs_uri: Optional[str] = None
    bucket: Optional[str] = None
    object: Optional[str] = None


class Task(BaseModel):
    id: str
    model: str
    status: str
    created_at: int
    updated_at: int
    content: Optional[TaskContent] = None
    resolution: str
    duration: int
    ratio: str
    task_type: str = "generation"
    modality: str = "video"
    mode: str
    workflow_type: str
    scheduler_state: Optional[str] = None
    usage: Optional[TaskUsage] = None
    metrics: Optional[TaskMetrics] = None
    error: Optional[dict] = None


class QueryResponse(BaseModel):
    task: Task


class ClaimRequest(BaseModel):
    worker_session_id: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    workflow_revision: str = Field(min_length=1, max_length=128)


class LeaseRequest(ClaimRequest):
    lease_token: str = Field(min_length=16, max_length=256)


class HeartbeatRequest(LeaseRequest):
    phase: Literal['leased', 'running', 'uploading'] = 'leased'
    comfy_prompt_id: Optional[str] = Field(default=None, max_length=128)


class RecoverRequest(BaseModel):
    task_id: str = Field(pattern=r'^gen_[a-f0-9]{32}$')
    lease_token: str = Field(min_length=16, max_length=256)
    old_worker_session_id: str = Field(min_length=1, max_length=128)
    new_worker_session_id: str = Field(min_length=1, max_length=128)
    workflow_revision: str = Field(min_length=1, max_length=128)


class FailureRequest(LeaseRequest):
    code: Literal['INVALID_REQUEST', 'SUBMISSION_UNCERTAIN', 'COMFYUI_UNAVAILABLE',
                  'INFERENCE_FAILED', 'GCS_UPLOAD_FAILED', 'RESULT_VERIFICATION_FAILED']

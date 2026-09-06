from typing import Literal, Optional
from pydantic import BaseModel, Field


class ContentItem(BaseModel):
    type: Literal["text", "image_url"]
    text: Optional[str] = None
    role: Optional[Literal["first_frame", "last_frame"]] = None
    image_url: Optional[str] = None


class CreateVideoRequest(BaseModel):
    model: str
    mode: Literal["realtime", "batch"]
    content: list[ContentItem]
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

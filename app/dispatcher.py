import logging
import subprocess
import threading
import time

from app import comfy_client, config
from app.errors import ApiError
from app.gcs_uploader import upload_video
from app.job_store import job_store
from app.scheduler import scheduler
from app.workflow import build_prompt_graph
from app.workflow_router import resolve_workflow, validate_resolution
from app.scheduler import ACTIVE_STATUSES

logger = logging.getLogger("dispatcher")

# task_id -> comfy_prompt_id, for jobs currently occupying a ComfyUI slot.
# Reconstructed from the job store on startup so a restart doesn't orphan
# jobs that were already submitted to ComfyUI before the process died.
_in_flight: dict[str, str] = {
    job["task_id"]: job["comfy_prompt_id"]
    for job in job_store.all_jobs()
    if job.get("status") in ACTIVE_STATUSES and job.get("comfy_prompt_id")
}


def _finalize_job(task_id: str, prompt_id: str):
    history = comfy_client.get_history(prompt_id)
    if history is None:
        return  # not finished yet

    status = history.get("status", {})
    if status.get("status_str") == "error":
        job_store.update(task_id, status="failed", scheduler_state=None,
                          error={"code": "INFERENCE_FAILED", "message": str(status)})
        _in_flight.pop(task_id, None)
        return

    if not status.get("completed"):
        return  # still running

    job = job_store.get(task_id)
    outputs = history.get("outputs", {}).get(job["save_node"], {})
    videos = outputs.get("videos") or outputs.get("gifs") or outputs.get("images") or []
    if not videos:
        job_store.update(task_id, status="failed", scheduler_state=None,
                          error={"code": "INFERENCE_FAILED", "message": "no video output produced"})
        _in_flight.pop(task_id, None)
        return

    video_info = videos[0]
    local_path = str(config.COMFY_OUTPUT_DIR / video_info.get("subfolder", "") / video_info["filename"])

    job_store.update(task_id, status="uploading", scheduler_state="uploading", local_output_file=local_path)

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", local_path],
        capture_output=True, text=True,
    )
    if probe.returncode != 0 or not probe.stdout.strip():
        job_store.update(task_id, status="failed", scheduler_state=None,
                          error={"code": "INFERENCE_FAILED", "message": f"ffprobe validation failed: {probe.stderr}"})
        _in_flight.pop(task_id, None)
        return

    try:
        gcs_uri, bucket, object_name = upload_video(local_path, task_id)
    except Exception as e:
        job_store.update(task_id, status="failed", scheduler_state=None,
                          error={"code": "GCS_UPLOAD_FAILED", "message": str(e)})
        _in_flight.pop(task_id, None)
        return

    job_store.update(
        task_id, status="succeeded", scheduler_state=None,
        gcs_uri=gcs_uri, gcs_bucket=bucket, gcs_object=object_name,
    )
    _in_flight.pop(task_id, None)


def _submit_next():
    task_id = scheduler.pop_next()
    if task_id is None:
        return False

    job = job_store.get(task_id)
    try:
        entry = resolve_workflow(job["model"], job["workflow_type"])
        resolution_preset = validate_resolution(job["model"], job["request"]["resolution"])
        from app.schemas import CreateVideoRequest
        req = CreateVideoRequest(model=job["model"], **job["request"])
        graph = build_prompt_graph(req, job["workflow_type"], entry["workflow_file"], task_id, resolution_preset)
    except ApiError as e:
        logger.warning("job %s failed request-level validation/build: %s", task_id, e.detail)
        error = dict(e.detail.get("error", {}))
        job_store.update(task_id, status="failed", scheduler_state=None,
                          error={"code": error.get("code", "INVALID_REQUEST"), "message": error.get("message", str(e))})
        return True
    except Exception as e:
        logger.exception("unexpected error building graph for job %s", task_id)
        job_store.update(task_id, status="failed", scheduler_state=None,
                          error={"code": "INFERENCE_FAILED", "message": str(e)})
        return True

    try:
        prompt_id = comfy_client.submit_prompt(graph, client_id=task_id)
    except Exception as e:
        logger.exception("ComfyUI rejected/unreachable for job %s", task_id)
        job_store.update(task_id, status="failed", scheduler_state=None,
                          error={"code": "COMFYUI_UNAVAILABLE", "message": str(e)})
        return True

    job_store.update(task_id, status="prefetched", scheduler_state="prefetched",
                      comfy_prompt_id=prompt_id, save_node="92")
    _in_flight[task_id] = prompt_id
    return True


def _tick():
    for task_id, prompt_id in list(_in_flight.items()):
        try:
            _finalize_job(task_id, prompt_id)
        except Exception:
            logger.exception("error finalizing job %s", task_id)

    try:
        active = comfy_client.get_queue_depth()
    except Exception:
        logger.exception("failed to read ComfyUI queue depth")
        return

    while active < config.MAX_COMFY_ACTIVE:
        submitted = _submit_next()
        if not submitted:
            break
        active += 1


def _run():
    while True:
        try:
            _tick()
        except Exception:
            logger.exception("dispatcher tick failed")
        time.sleep(config.DISPATCHER_POLL_INTERVAL_SECONDS)


def start():
    thread = threading.Thread(target=_run, daemon=True, name="dispatcher")
    thread.start()
    return thread

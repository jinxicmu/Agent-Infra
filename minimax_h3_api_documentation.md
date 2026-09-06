# MiniMax H3 Video Generation API (self-hosted)

A MiniMax-Video-Generation-V2-style API for AI Studio's self-hosted ComfyUI MiniMax H3 pipeline.

> **Current deployment status:** the service is running and validated, reachable at `http://127.0.0.1:8000` on the RunPod host. Public network exposure (RunPod proxy / Cloudflare Tunnel) has not been set up yet — talk to the AI Studio team for the current reachable base URL for your environment. Examples below use `$AI_STUDIO_API_BASE` as a placeholder.
>
> **Currently enabled workflow:** `fl2v` only (text + first-frame + last-frame image → video). `t2v` and single-image `i2v` are implemented in the same code path but disabled until a validated checkpoint exists for them; requests routed to a disabled workflow type return `400 UNSUPPORTED_WORKFLOW_COMBINATION`.

---

## Authentication

All endpoints except `/healthz` require a bearer token:

```
Authorization: Bearer <AI_STUDIO_API_KEY>
```

Contact the AI Studio team for a key. Requests with a missing or invalid key get `401 AUTH_FAILED`.

## Base endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/v2/video_generation` | Submit a video generation task |
| GET | `/v2/query/video_generation?task_id=...` | Check status / get the result |
| GET | `/healthz` | Liveness check (no auth required) |

---

## Quick example: generate a video from two frames (fl2v)

The only enabled mode today takes one text prompt plus a `first_frame` and a `last_frame` image, and animates the transition between them.

### curl

```bash
export AI_STUDIO_API_BASE="http://127.0.0.1:8000"   # replace with your reachable base URL
export AI_STUDIO_API_KEY="<your key>"

# 1. Submit
TASK_ID=$(curl -sS -X POST "$AI_STUDIO_API_BASE/v2/video_generation" \
  -H "Authorization: Bearer $AI_STUDIO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "MiniMax-H3",
    "mode": "realtime",
    "content": [
      {"type": "text", "text": "A gentle transition from a mountain sunrise to a calm alpine lake."},
      {"type": "image_url", "role": "first_frame", "image_url": "https://example.com/sunrise.jpg"},
      {"type": "image_url", "role": "last_frame", "image_url": "https://example.com/lake.jpg"}
    ],
    "resolution": "768P",
    "duration": 5,
    "ratio": "adaptive"
  }' | python3 -c "import json,sys; print(json.load(sys.stdin)['task_id'])")

echo "task_id: $TASK_ID"

# 2. Poll until done
until curl -sS "$AI_STUDIO_API_BASE/v2/query/video_generation?task_id=$TASK_ID" \
    -H "Authorization: Bearer $AI_STUDIO_API_KEY" \
    | tee /tmp/result.json | python3 -c "import json,sys; s=json.load(sys.stdin)['task']['status']; exit(0 if s in ('succeeded','failed') else 1)"; do
  sleep 5
done
python3 -m json.tool /tmp/result.json
```

### Python

```python
import time
import requests

BASE = "http://127.0.0.1:8000"   # replace with your reachable base URL
KEY = "<your key>"
HEADERS = {"Authorization": f"Bearer {KEY}"}

resp = requests.post(f"{BASE}/v2/video_generation", headers=HEADERS, json={
    "model": "MiniMax-H3",
    "mode": "realtime",  # "realtime" for latency-sensitive requests, "batch" for lower-priority bulk work
    "content": [
        {"type": "text", "text": "A gentle transition from a mountain sunrise to a calm alpine lake."},
        {"type": "image_url", "role": "first_frame", "image_url": "https://example.com/sunrise.jpg"},
        {"type": "image_url", "role": "last_frame", "image_url": "https://example.com/lake.jpg"},
    ],
    "resolution": "768P",
    "duration": 5,
    "ratio": "adaptive",
})
resp.raise_for_status()
task_id = resp.json()["task_id"]
print("task_id:", task_id)

while True:
    r = requests.get(f"{BASE}/v2/query/video_generation", headers=HEADERS, params={"task_id": task_id})
    task = r.json()["task"]
    if task["status"] in ("succeeded", "failed"):
        break
    time.sleep(5)

if task["status"] == "succeeded":
    print("done:", task["content"]["gcs_uri"])
else:
    print("failed:", task["error"])
```

There is no download endpoint — completed videos live at the returned `gcs_uri` (a GCS object your backend already has access to). Retrieve them with your existing GCS credentials, e.g.:

```bash
gcloud storage cp gs://self_deployed_model_working_dir/generated_video_dir/<task_id>.mp4 .
```

---

## Request schema (`POST /v2/video_generation`)

| Field | Type | Required | Notes |
|---|---|---|---|
| `model` | string | yes | `"MiniMax-H3"` (`"MiniMax-H3-Max"` is not installed on this deployment) |
| `mode` | `"realtime"` \| `"batch"` | yes | `realtime` = latency-sensitive; `batch` = lower-priority. Realtime always gets the next free execution slot ahead of batch (non-preemptive — a running batch job is never interrupted). |
| `content` | array | yes | Exactly one `text` item, plus 0–2 `image_url` items (see below) |
| `resolution` | string | yes | Only `"768P"` is currently enabled |
| `duration` | integer | yes | Only `5` (seconds) is currently enabled |
| `ratio` | string | yes | Only `"adaptive"` is accepted for the enabled `fl2v` workflow — it derives width/height from the input image itself. A concrete ratio (e.g. `"16:9"`) is rejected with `400 INVALID_RATIO_FOR_WORKFLOW`. |
| `callback_url` | string | no | **Not implemented** — including it returns `400 UNSUPPORTED_PARAMETER` |
| `metadata` | object | no | Freeform (e.g. your own campaign/creative IDs); passed through untouched, never affects routing or inference |

### `content` items

```json
{"type": "text", "text": "..."}
```
```json
{"type": "image_url", "role": "first_frame" | "last_frame", "image_url": "https://..."}
```

- Image URLs must be publicly resolvable `http(s)` URLs — private/loopback/reserved addresses are rejected (`400 INVALID_REQUEST`) as an SSRF guard, and this check happens when the job is dispatched, not at submission time.
- Content shape determines the workflow (today, only the shape below is enabled):

| Content shape | workflow_type | Enabled? |
|---|---|---|
| text only | `t2v` | no |
| text + first_frame | `i2v_first` | no |
| text + last_frame | `i2v_last` | no |
| text + first_frame + last_frame | `fl2v` | **yes** |

### Create response

```json
{"task_id": "gen_...", "status": "accepted", "mode": "realtime"}
```

---

## Query response (`GET /v2/query/video_generation?task_id=...`)

```json
{
  "task": {
    "id": "gen_...",
    "model": "MiniMax-H3",
    "status": "succeeded",
    "created_at": 1788509987,
    "updated_at": 1788510044,
    "content": {
      "gcs_uri": "gs://self_deployed_model_working_dir/generated_video_dir/gen_....mp4",
      "bucket": "self_deployed_model_working_dir",
      "object": "generated_video_dir/gen_....mp4"
    },
    "resolution": "768P",
    "duration": 5,
    "ratio": "adaptive",
    "task_type": "generation",
    "modality": "video",
    "mode": "realtime",
    "workflow_type": "fl2v",
    "scheduler_state": null,
    "usage": {"input_image_count": 2, "output_seconds": 5},
    "error": null
  }
}
```

`status` is one of: `queued`, `running`, `succeeded`, `failed`, `cancelled`. `content` is only populated once `status` is `succeeded`. On failure, `error` is `{"code": "...", "message": "..."}`.

---

## Error format

All errors (except FastAPI-level body parsing, which uses the same shape) look like:

```json
{
  "type": "error",
  "error": {"type": "bad_request_error", "message": "human-readable message", "http_code": "400", "code": "SOME_CODE"},
  "request_id": "req_..."
}
```

| HTTP | code | Meaning |
|---|---|---|
| 400 | `INVALID_REQUEST` | Malformed content, bad image URL, etc. |
| 400 | `INVALID_MODE` | `mode` not `realtime`/`batch` |
| 400 | `UNSUPPORTED_MODEL` | Model not installed/validated |
| 400 | `UNSUPPORTED_WORKFLOW_COMBINATION` | Content shape maps to a disabled or unrecognized workflow_type |
| 400 | `UNSUPPORTED_CONTENT_ROLE` | Unrecognized image `role` |
| 400 | `INVALID_RATIO_FOR_WORKFLOW` | `ratio` not allowed for this workflow_type |
| 400 | `UNSUPPORTED_DURATION` | `duration` not in the enabled preset set |
| 400 | `UNSUPPORTED_RESOLUTION` | `resolution` not in the enabled preset set |
| 400 | `UNSUPPORTED_PARAMETER` | Used an unimplemented field (e.g. `callback_url`) |
| 400 | `QUEUE_FULL` | Too many pending tasks for this mode |
| 401 | `AUTH_FAILED` | Missing/invalid bearer token |
| 404 | `TASK_NOT_FOUND` | Unknown `task_id` |
| 500 | `COMFYUI_UNAVAILABLE` | ComfyUI rejected or was unreachable at dispatch time |
| 500 | `GCS_UPLOAD_FAILED` | Render succeeded but upload to GCS failed |
| 500 | `INFERENCE_FAILED` | Render itself failed |

---

## Scheduling notes for clients

- Use `mode: "realtime"` for interactive/user-facing requests and `mode: "batch"` for bulk/background generation — realtime always gets priority for the next execution slot, but a job that's already running is never interrupted, so a `batch` request in flight will finish normally even if `realtime` requests arrive afterward.
- There's no notion of "position in queue" exposed today — poll `GET /v2/query/video_generation` until `status` leaves `queued`/`running`.
- Typical generation time for a 5-second 768P clip is on the order of 1–2 minutes; plan client-side polling/backoff accordingly (e.g. every 5 seconds).

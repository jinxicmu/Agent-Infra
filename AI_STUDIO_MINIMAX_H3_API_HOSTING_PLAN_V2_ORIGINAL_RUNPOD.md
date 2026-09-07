# Archived RunPod plan — historical reference only

This is the superseded original V2 RunPod document, preserved verbatim below. Its execution instructions are historical and must not be used to implement the Cloud Run/local-worker deployment. Codex must use `AI_STUDIO_MINIMAX_H3_API_HOSTING_PLAN_V2.md` for that deployment.

---

# AI Studio — MiniMax H3 API Hosting Plan V2
**Target:** RunPod RTX 5090 or Local RTX 5090 Workstation  
**Inference engine:** Existing working ComfyUI MiniMax H3 workflows  
**Public service:** FastAPI asynchronous video-generation API  
**Version:** V2 — MiniMax-style public API + workflow routing + `realtime` / `batch` scheduling + GCS output

---

# 1. Mission

Redesign the public API so it is **modeled after MiniMax Video Generation V2**, while still using **self-hosted ComfyUI workflows** underneath.

This plan must support multiple generation workflows:

- `t2v`
- `i2v`
- `fl2v`

The public API should look close to MiniMax's Video Generation V2 create endpoint, but only expose the subset that the local ComfyUI deployment actually supports.

The system must also support two scheduling modes:

- `realtime` — latency-sensitive Studio requests
- `batch` — lower-priority Drama Maker batch requests

The scheduler must keep **at most 2 tasks inside ComfyUI**:

- `1 Running`
- `1 Prefetched`

This reduces idle time between jobs while still preserving scheduler control.

All successful outputs must be uploaded to:

```text
gs://self_deployed_model_working_dir/generated_video_dir/
```

No public video-download endpoint is required.

---

# 2. External API philosophy

The API should be compatible in spirit with MiniMax Video Generation V2:

- `POST /v2/video_generation`
- bearer auth
- `model`
- `content` array
- `resolution`
- `duration`
- `ratio`
- return `task_id`

But the backend implementation is different:

```text
Public API
  -> API-owned validation
  -> API-owned queue / scheduler
  -> route to matching ComfyUI workflow
  -> ComfyUI executes
  -> upload MP4 to GCS
  -> task query returns GCS object location
```

---

# 3. High-level architecture

```text
AI Studio / Novvy Backend
          |
          | HTTPS
          v
+-----------------------------------+
| FastAPI Gateway                   |
|                                   |
| POST /v2/video_generation         |
| GET  /v2/query/video_generation   |
| GET  /healthz                     |
+----------------+------------------+
                 |
                 v
+-----------------------------------+
| API Job Store + Scheduler         |
|                                   |
| queue owned by API                |
| modes: realtime / batch           |
| dispatch policy owned by API      |
+----------------+------------------+
                 |
                 v
+-----------------------------------+
| Workflow Router                   |
|                                   |
| content -> workflow selection     |
| t2v / i2v / fl2v                  |
+----------------+------------------+
                 |
                 v
+-----------------------------------+
| ComfyUI :8188                     |
|                                   |
| max 2 tasks inside queue          |
| 1 running + 1 prefetched          |
+----------------+------------------+
                 |
                 v
             RTX 5090
                 |
                 v
+-----------------------------------+
| GCS Uploader                      |
|                                   |
| gs://self_deployed_model_...      |
+-----------------------------------+
```

---

# 4. Core design rules

1. **Public callers never submit arbitrary workflow JSON.**
2. **API owns scheduling.**
3. **ComfyUI only executes approved workflows.**
4. **Workflow selection is based on validated request content.**
5. **ComfyUI queue depth must not exceed 2 active tasks.**
6. **`realtime` outranks `batch`, but there is no mid-render preemption.**
7. **A task is not `succeeded` until the MP4 is uploaded to GCS and the object is verified.**

---

# 5. Public API surface

The public API surface is:

```text
POST /v2/video_generation
GET  /v2/query/video_generation?task_id=...
GET  /healthz
```

There is no `GET /video content` endpoint.

The query endpoint returns task status and, when complete, the GCS object location.

---

# 6. Public create endpoint

## 6.1 Endpoint

```text
POST /v2/video_generation
```

## 6.2 Authentication

```text
Authorization: Bearer <AI_STUDIO_API_KEY>
Content-Type: application/json
```

## 6.3 Request body

Adopt a MiniMax-style schema.

Example — text-to-video:

```json
{
  "model": "MiniMax-H3",
  "mode": "realtime",
  "content": [
    {
      "type": "text",
      "text": "A cinematic shot of a woman turning toward camera and smiling naturally."
    }
  ],
  "resolution": "768P",
  "duration": 5,
  "ratio": "16:9"
}
```

Example — first-frame image-to-video:

```json
{
  "model": "MiniMax-H3",
  "mode": "realtime",
  "content": [
    {
      "type": "text",
      "text": "The woman slowly turns her head toward camera."
    },
    {
      "type": "image_url",
      "role": "first_frame",
      "image_url": "https://cdn.example.com/frame.png"
    }
  ],
  "resolution": "768P",
  "duration": 5,
  "ratio": "adaptive"
}
```

Example — first+last frame FL2V:

```json
{
  "model": "MiniMax-H3",
  "mode": "batch",
  "content": [
    {
      "type": "text",
      "text": "A gentle transition from sadness to relief."
    },
    {
      "type": "image_url",
      "role": "first_frame",
      "image_url": "https://cdn.example.com/first.png"
    },
    {
      "type": "image_url",
      "role": "last_frame",
      "image_url": "https://cdn.example.com/last.png"
    }
  ],
  "resolution": "768P",
  "duration": 5,
  "ratio": "adaptive",
  "metadata": {
    "batch_id": "drama_batch_001"
  }
}
```

## 6.4 Create response

Return MiniMax-style:

```json
{
  "task_id": "gen_01abc..."
}
```

Optionally include extra internal-compatible fields if useful:

```json
{
  "task_id": "gen_01abc...",
  "status": "accepted",
  "mode": "realtime"
}
```

But `task_id` must remain the primary identifier.

---

# 7. Public query endpoint

## 7.1 Endpoint

```text
GET /v2/query/video_generation?task_id=<TASK_ID>
```

## 7.2 Query response shape

Return a MiniMax-like task object:

```json
{
  "task": {
    "id": "gen_01abc...",
    "model": "MiniMax-H3",
    "status": "succeeded",
    "created_at": 1785125529,
    "updated_at": 1785125946,
    "content": {
      "gcs_uri": "gs://self_deployed_model_working_dir/generated_video_dir/gen_01abc....mp4",
      "bucket": "self_deployed_model_working_dir",
      "object": "generated_video_dir/gen_01abc....mp4"
    },
    "resolution": "768P",
    "duration": 5,
    "ratio": "16:9",
    "task_type": "generation",
    "modality": "video",
    "mode": "realtime",
    "workflow_type": "t2v",
    "usage": {
      "input_image_count": 0,
      "output_seconds": 5
    },
    "metrics": {
      "queue_time_ms": 900,
      "inference_time_ms": 48000,
      "upload_time_ms": 1600,
      "total_time_ms": 50500
    }
  }
}
```

---

# 8. Public request schema

## 8.1 `model`

Type:

```text
string
```

Required.

V1 allowed values:

```text
MiniMax-H3
MiniMax-H3-Max
```

But availability must match the actual self-hosted workflows on the machine.

If only `MiniMax-H3` workflows are installed and validated, reject `MiniMax-H3-Max`.

Do not claim support for a model unless the matching ComfyUI workflow exists and is tested.

---

## 8.2 `mode`

Type:

```text
enum
```

Required.

Allowed values:

```text
realtime
batch
```

Meaning:

- `realtime` = latency-sensitive Studio request
- `batch` = lower-priority Drama Maker request

This replaces the previous `p0` / `p1` naming.

---

## 8.3 `content`

Type:

```text
array
```

Required.

The schema should intentionally resemble MiniMax V2.

Every request must include exactly one non-empty `text` item.

Supported item types for this self-hosted API baseline:

### text item

```json
{
  "type": "text",
  "text": "Prompt here"
}
```

### image item

```json
{
  "type": "image_url",
  "role": "first_frame",
  "image_url": "https://..."
}
```

Supported image roles:

```text
first_frame
last_frame
```

Unsupported in this initial self-hosted baseline:

```text
reference_image
reference_video
reference_audio
video_url
audio_url
```

If those appear, reject with:

```text
400 UNSUPPORTED_CONTENT_ROLE
```

or:

```text
400 UNSUPPORTED_CONTENT_TYPE
```

until a matching ComfyUI workflow is implemented.

---

## 8.4 Supported workflow combinations inferred from `content`

The API must infer `workflow_type` from the content array.

### 8.4.1 Text-to-video (`t2v`)

Allowed content:

```text
[text]
```

Rule:

- exactly one `text`
- no image items

Dispatch to:

```text
T2V workflow
```

---

### 8.4.2 Image-to-video first-frame (`i2v_first`)

Allowed content:

```text
[text, image_url(role=first_frame)]
```

Also allow omitted role and treat it as `first_frame` if exactly one image is present and no other image role is present.

Dispatch to:

```text
I2V first-frame workflow
```

---

### 8.4.3 Image-to-video last-frame (`i2v_last`)

Allowed content:

```text
[text, image_url(role=last_frame)]
```

Dispatch to:

```text
I2V last-frame workflow
```

Only enable if that specific ComfyUI workflow actually exists and passes validation.

If it does not exist, reject with:

```text
400 UNSUPPORTED_WORKFLOW_COMBINATION
```

---

### 8.4.4 First+last-frame video (`fl2v`)

Allowed content:

```text
[text, image_url(role=first_frame), image_url(role=last_frame)]
```

Rules:

- exactly one first frame
- exactly one last frame

Dispatch to:

```text
FL2V workflow
```

---

## 8.5 `resolution`

Type:

```text
enum
```

Allowed only if backed by validated workflow presets.

Possible values:

```text
480P
768P
2K
```

Do not expose a resolution if the current workflow stack on the machine has not been validated for it.

Use server-side preset mapping:

```json
{
  "MiniMax-H3": {
    "768P": {...},
    "2K": {...}
  },
  "MiniMax-H3-Max": {
    "480P": {...},
    "768P": {...}
  }
}
```

---

## 8.6 `duration`

Type:

```text
integer
```

Should mirror MiniMax-style duration input.

Possible values by model in MiniMax docs are 4–15 for `MiniMax-H3` and 5–15 for `MiniMax-H3-Max`.

For the self-hosted API, only expose durations that map to validated ComfyUI presets.

Do **not** compute frame count using `duration * fps` blindly.

Instead use explicit preset mapping:

```json
{
  "MiniMax-H3": {
    "5": {
      "frames": 124,
      "fps": 24
    }
  }
}
```

If unsupported:

```text
400 UNSUPPORTED_DURATION
```

---

## 8.7 `ratio`

Type:

```text
enum
```

Allowed public values:

```text
adaptive
21:9
16:9
4:3
1:1
3:4
9:16
```

Behavior:

### T2V
- `ratio` is required
- `adaptive` is not allowed

### I2V / FL2V
- only `adaptive` should be accepted publicly
- if a concrete ratio is provided, either:
  - reject it, or
  - normalize it to `adaptive` explicitly and document this behavior

Recommended for self-hosted consistency:

- **accept only `adaptive` for I2V / FL2V**
- reject other ratios with `400 INVALID_RATIO_FOR_WORKFLOW`

This is cleaner than silently ignoring.

---

## 8.8 `callback_url`

Optional.

If implemented, it should behave similarly to MiniMax:
- task status changes trigger callback
- supported statuses: `queued`, `running`, `succeeded`, `failed`, `cancelled`

For the first baseline, callback support is optional. If not implemented, reject with:

```text
400 UNSUPPORTED_PARAMETER
```

Do not silently ignore.

---

## 8.9 `metadata`

Optional JSON object.

Use for:
- Studio identifiers
- batch identifiers
- campaign IDs
- creative IDs

Metadata must not affect workflow routing or inference parameters.

---

# 9. Workflow routing

Create a workflow router.

## 9.1 Required files

```text
app/workflow_router.py
workflows/WORKFLOW_REGISTRY.json
workflows/PARAMETER_MAP.<workflow>.json
workflows/PRESETS.json
```

## 9.2 Workflow registry

The service must maintain an explicit registry of validated workflows.

Example:

```json
{
  "MiniMax-H3": {
    "t2v": {
      "workflow_file": "minimax_h3_t2v_api.json",
      "enabled": true
    },
    "i2v_first": {
      "workflow_file": "minimax_h3_i2v_first_api.json",
      "enabled": true
    },
    "i2v_last": {
      "workflow_file": "minimax_h3_i2v_last_api.json",
      "enabled": false
    },
    "fl2v": {
      "workflow_file": "minimax_h3_fl2v_api.json",
      "enabled": true
    }
  }
}
```

## 9.3 Routing rule

```text
(model, inferred workflow_type, resolution, duration, ratio)
    -> workflow registry
    -> workflow file
    -> parameter map
    -> patched prompt graph
```

Never pick a workflow implicitly from fuzzy heuristics beyond the deterministic `content` rules above.

---

# 10. Why the API must own the queue

Because the service now supports:

- multiple workflows
- two scheduling modes
- controlled queue depth inside ComfyUI

the API must own the queue and dispatch policy.

Do **not** immediately submit every request to ComfyUI.

Correct design:

```text
POST request
  -> validate
  -> persist task
  -> place in API queue
  -> scheduler decides when to submit to ComfyUI
```

ComfyUI remains the execution backend, not the system-of-record scheduler.

---

# 11. Scheduling model

## 11.1 Modes

Two modes:

- `realtime`
- `batch`

## 11.2 Policy

Use non-preemptive priority:

1. `realtime` outranks `batch`
2. if any `realtime` task is waiting and a prefetch slot is available, fill it with the oldest waiting `realtime`
3. otherwise fill with the oldest waiting `batch`
4. never interrupt a currently running task

So if a `batch` task is running and a `realtime` task arrives:

```text
current batch continues
next task prefetched / dispatched should be realtime
```

---

# 12. ComfyUI queue depth policy

This is a new explicit requirement.

Maintain:

```text
max tasks inside ComfyUI queue = 2
```

Specifically:

- **1 Running**
- **1 Prefetched**

This means the API scheduler must monitor ComfyUI queue state and only keep enough work inside ComfyUI to satisfy this invariant.

Interpretation:

- If nothing is running and nothing is queued in ComfyUI, submit one task immediately.
- If one task is already running and ComfyUI has no pending next task, submit one more prefetched task.
- If ComfyUI already has one running and one queued, do not submit more.

This reduces idle gaps after a job finishes but preserves enough upstream scheduler control.

---

# 13. Prefetch semantics

A **prefetched** task is:

- already submitted into ComfyUI
- not yet running
- occupies the one allowed pending slot

API status mapping:

- internal status = `prefetched`
- public status may still show `queued`, or optionally `queued` plus metadata

Recommended internal states:

```text
accepted
queued
prefetched
running
uploading
succeeded
failed
cancelled
```

Recommended public states:

```text
queued
running
succeeded
failed
cancelled
```

If desired, expose a richer `scheduler_state` field:

```json
{
  "task": {
    "status": "queued",
    "scheduler_state": "prefetched"
  }
}
```

---

# 14. Anti-starvation guidance

V1 may use simple mode-priority dispatch:

```text
realtime first, then batch
```

However, because `realtime` may dominate traffic, log the wait time of `batch` tasks.

If batch starvation becomes real later, the next evolution could be:

- aging
- weighted scheduling
- dedicated worker pools

Do not implement those yet unless necessary.

---

# 15. Job persistence

Store one JSON file per task.

Example path:

```text
jobs/<task_id>.json
```

Example contents:

```json
{
  "task_id": "gen_01abc...",
  "model": "MiniMax-H3",
  "mode": "realtime",
  "workflow_type": "i2v_first",
  "status": "queued",
  "scheduler_state": "queued",
  "created_at": 1785125529,
  "updated_at": 1785125530,
  "request": {
    "resolution": "768P",
    "duration": 5,
    "ratio": "adaptive"
  },
  "comfy_prompt_id": null,
  "input_assets": [],
  "local_output_file": null,
  "gcs_uri": null,
  "gcs_bucket": null,
  "gcs_object": null,
  "error": null,
  "metadata": {
    "creative_id": "c_123"
  }
}
```

Use atomic writes.

The queue must be reconstructable from disk after restart.

---

# 16. GCS output

Every successful task must upload its MP4 to:

```text
gs://self_deployed_model_working_dir/generated_video_dir/<task_id>.mp4
```

Required environment variables:

```text
GCP_PROJECT=novvy-dev
GCS_OUTPUT_BUCKET=self_deployed_model_working_dir
GCS_OUTPUT_PREFIX=generated_video_dir
```

A task becomes `succeeded` only after:

1. ComfyUI output is located
2. `ffprobe` validates the MP4
3. the file uploads to GCS
4. object existence is verified

If upload fails:

```text
status = failed
error.code = GCS_UPLOAD_FAILED
```

---

# 17. Supported errors

Use a consistent error schema:

```json
{
  "type": "error",
  "error": {
    "type": "bad_request_error",
    "message": "Human-readable message",
    "http_code": "400"
  },
  "request_id": "req_..."
}
```

Suggested error codes/messages:

- `INVALID_REQUEST`
- `INVALID_MODE`
- `UNSUPPORTED_MODEL`
- `UNSUPPORTED_CONTENT_TYPE`
- `UNSUPPORTED_CONTENT_ROLE`
- `UNSUPPORTED_WORKFLOW_COMBINATION`
- `INVALID_RATIO_FOR_WORKFLOW`
- `UNSUPPORTED_DURATION`
- `UNSUPPORTED_RESOLUTION`
- `AUTH_FAILED`
- `QUEUE_FULL`
- `TASK_NOT_FOUND`
- `COMFYUI_UNAVAILABLE`
- `GCS_UPLOAD_FAILED`
- `INFERENCE_FAILED`

---

# 18. Durable directory layout

RunPod default:

```text
/workspace/ai_studio_api_v2
```

Local workstation default:

```text
~/ai_studio_api_v2
```

Structure:

```text
<API_ROOT>/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── auth.py
│   ├── config.py
│   ├── schemas.py
│   ├── workflow_router.py
│   ├── workflow.py
│   ├── comfy_client.py
│   ├── image_fetcher.py
│   ├── scheduler.py
│   ├── dispatcher.py
│   ├── gcs_uploader.py
│   └── job_store.py
├── workflows/
│   ├── WORKFLOW_REGISTRY.json
│   ├── PRESETS.json
│   ├── minimax_h3_t2v_api.json
│   ├── minimax_h3_i2v_first_api.json
│   ├── minimax_h3_i2v_last_api.json
│   ├── minimax_h3_fl2v_api.json
│   ├── PARAMETER_MAP.t2v.json
│   ├── PARAMETER_MAP.i2v_first.json
│   ├── PARAMETER_MAP.i2v_last.json
│   └── PARAMETER_MAP.fl2v.json
├── jobs/
├── inputs/
├── outputs/
├── logs/
├── tests/
├── requirements.txt
├── .env.example
└── README.md
```

---

# 19. Environment variables

Example:

```bash
HOSTING_MODE=runpod

AI_STUDIO_API_KEY=replace_me

COMFY_BASE_URL=http://127.0.0.1:8188

GCP_PROJECT=novvy-dev
GCS_OUTPUT_BUCKET=self_deployed_model_working_dir
GCS_OUTPUT_PREFIX=generated_video_dir
KEEP_LOCAL_OUTPUTS=true

MAX_PENDING_REALTIME=20
MAX_PENDING_BATCH=200
MAX_TOTAL_PENDING=220
MAX_COMFY_ACTIVE=2

MAX_INPUT_IMAGE_MB=20
IMAGE_DOWNLOAD_TIMEOUT_SECONDS=20
MAX_IMAGE_REDIRECTS=3

LOG_PROMPTS=false
JOB_RETENTION_HOURS=168
DISPATCHER_POLL_INTERVAL_SECONDS=2
```

For local deployment, use:

```bash
HOSTING_MODE=local
```

`MAX_COMFY_ACTIVE` must be `2` for this plan.

---

# 20. Required implementation detail: queue accounting

The dispatcher must count ComfyUI active slots as:

```text
active_in_comfy = running_count + queued_count
```

Target invariant:

```text
active_in_comfy <= 2
```

And:

```text
target running = 1
target queued/prefetched = 1
```

Pseudo-logic:

```text
while active_in_comfy < 2:
    choose next task by mode priority
    submit to ComfyUI
    mark scheduler_state = prefetched or running as appropriate
```

If ComfyUI has:
- 0 running, 0 queued -> submit up to 1 immediately, then optionally a 2nd if the first transitions appropriately
- 1 running, 0 queued -> submit 1 prefetched
- 1 running, 1 queued -> submit none
- 0 running, 1 queued -> let ComfyUI start it; do not flood more unless safe

The implementation should be conservative and avoid overfilling the queue.

---

# 21. Required implementation detail: workflow extraction

For every supported workflow (`t2v`, `i2v_first`, `i2v_last`, `fl2v`):

1. run or locate a known-good ComfyUI execution
2. export the exact API-format workflow
3. store it in `workflows/`
4. identify runtime parameter nodes
5. save workflow-specific parameter maps

Do not reconstruct the graph manually.

Do not guess node IDs.

---

# 22. Phase plan for Claude Code

## Phase 0 — Host discovery
Determine:
- RunPod or local
- ComfyUI root
- ComfyUI python
- ComfyUI version / commit
- current bind / port
- current launch method
- durable API root

Verify ComfyUI is healthy.

Pass only if environment is identified.

---

## Phase 1 — Capture all supported workflows
Capture exact working workflows for:

- T2V
- I2V first-frame
- FL2V
- I2V last-frame (only if truly supported)

Store baseline copies.

Pass only if each claimed workflow has a durable API-format JSON.

---

## Phase 2 — Build workflow registry + parameter maps
Create:
- `WORKFLOW_REGISTRY.json`
- `PRESETS.json`
- `PARAMETER_MAP.*.json`

Pass only if every enabled workflow has positive mappings for prompt/image/seed/frames/resolution.

---

## Phase 3 — Raw ComfyUI API tests per workflow
For each enabled workflow:
1. upload required inputs
2. patch workflow
3. POST to `/prompt`
4. poll `/history/{prompt_id}`
5. verify MP4

Pass only if each enabled workflow reproduces successfully through ComfyUI API.

---

## Phase 4 — Build FastAPI public surface
Implement:
- `POST /v2/video_generation`
- `GET /v2/query/video_generation`
- `GET /healthz`

Pass only if request validation and response shapes match the V2 design.

---

## Phase 5 — Build scheduler + dispatcher
Implement:
- API-owned queue
- `realtime` / `batch`
- workflow routing
- Comfy queue depth max 2
- GCS upload

Pass only if one running + one prefetched invariant is observed.

---

## Phase 6 — Localhost end-to-end tests
Run:
- one `realtime` T2V
- one `realtime` I2V
- one `batch` FL2V
- priority ordering test
- queue-depth invariant test

Pass only if the API, scheduler, workflow router, ComfyUI, and GCS all work together.

---

## Phase 7A — RunPod public hosting
Expose FastAPI on port 8000 through RunPod HTTP proxy.

Pass only if public HTTPS create/query works.

---

## Phase 7B — Local public hosting
Expose FastAPI through Cloudflare Tunnel.

Pass only if public HTTPS create/query works and local ports remain private.

---

## Phase 8 — Recovery tests
Restart API layer.
Verify:
- tasks remain queryable
- queue reconstructs correctly
- scheduler resumes
- GCS references remain intact

Pass only if restart safety is proven.

---

# 23. Validation tests

Must test:

- valid T2V request
- valid I2V first-frame request
- valid FL2V request
- invalid content without text
- invalid mixed first_frame + unsupported reference inputs
- invalid ratio for T2V (`adaptive`)
- invalid non-adaptive ratio for I2V / FL2V
- invalid mode
- unsupported model
- private / localhost image URL
- queue full for `realtime`
- queue full for `batch`
- scheduler keeps at most 2 tasks inside ComfyUI
- when a `batch` is running and `realtime` arrives, next slot goes to `realtime`
- successful GCS upload
- GCS failure handling

---

# 24. Definition of done

Common:

```text
[ ] Existing ComfyUI UI generation still works
[ ] T2V workflow is captured and API-runnable
[ ] I2V workflow is captured and API-runnable
[ ] FL2V workflow is captured and API-runnable
[ ] I2V last-frame is either validated or explicitly disabled
[ ] Public API matches MiniMax-style create/query shape
[ ] `mode` uses `realtime` / `batch`
[ ] API owns the queue
[ ] Workflow routing is deterministic
[ ] ComfyUI queue depth never exceeds 2 active tasks
[ ] Scheduler enforces one running + one prefetched
[ ] `realtime` outranks `batch`
[ ] No mid-render preemption occurs
[ ] ffprobe validates output before upload
[ ] MP4 uploads to GCS
[ ] Query endpoint returns GCS location
[ ] Restart recovery works
```

RunPod:

```text
[ ] public RunPod proxy create/query works
```

Local:

```text
[ ] Cloudflare Tunnel create/query works
[ ] local ports remain private
```

---

# 25. Required deployment report

Write:

```text
<API_ROOT>/API_HOSTING_REPORT_V2.md
```

Template:

```markdown
# AI Studio MiniMax H3 API Hosting Report V2

## Host
- Date UTC:
- Hosting mode:
- GPU:
- OS:
- CUDA:
- PyTorch:

## ComfyUI
- Root:
- Python:
- Version/commit:
- Internal URL:
- Startup method:

## Supported workflows
- MiniMax-H3 T2V:
- MiniMax-H3 I2V first:
- MiniMax-H3 I2V last:
- MiniMax-H3 FL2V:
- MiniMax-H3-Max T2V:
- MiniMax-H3-Max I2V first:
- Disabled workflows and reasons:

## Public API
- Create endpoint:
- Query endpoint:
- Health endpoint:
- Auth:
- Request schema:
- Query schema:

## Scheduling
- Modes:
- Dispatch policy:
- Max pending realtime:
- Max pending batch:
- Max total pending:
- Max active in ComfyUI:
- Queue-depth invariant result:
- Priority-order test result:

## Workflow routing
- Registry path:
- T2V workflow file:
- I2V first workflow file:
- I2V last workflow file:
- FL2V workflow file:

## GCS
- Project:
- Bucket:
- Prefix:
- Credential method:
- Example output URI:

## Validation
- Raw T2V API test:
- Raw I2V API test:
- Raw FL2V API test:
- Public create/query test:
- Restart recovery:
- GCS upload verification:

## Final status
PASS / FAIL
```

---

# 26. Explicitly deferred

Do not mix these into this version unless separately approved:

- arbitrary reference-to-video inputs
- reference audio / video workflows
- download endpoint
- signed URLs
- webhook callbacks (unless you decide to add `callback_url`)
- Redis / Celery / Postgres
- multi-GPU scheduling
- autoscaling
- provider-wide central scheduler
- SageAttention tuning
- model optimization
- 4-step migration
- weighted fair scheduling
- mid-render preemption

---

# 27. Final instruction to Claude Code

Your job is to redesign the service so the **public API looks like MiniMax Video Generation V2**, while the **backend routes to the correct ComfyUI workflow**.

The order is:

```text
Identify working workflows
    ->
Export exact API-format workflow JSONs
    ->
Build workflow registry + parameter maps
    ->
Expose MiniMax-style create/query API
    ->
Add scheduler with mode = realtime / batch
    ->
Limit ComfyUI active depth to 2
    ->
Upload outputs to GCS
    ->
Validate end-to-end
```

Most important rules:

1. Public API is MiniMax-style.
2. Workflow selection is based on `content`.
3. `realtime` / `batch` are the scheduling modes.
4. ComfyUI keeps at most `1 Running + 1 Prefetched`.
5. Do not change the model stack while implementing this hosting layer.

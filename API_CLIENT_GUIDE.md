# Agent-Infra Video Generation API — Client Integration Guide

Last verified: 2026-09-06. This guide describes the deployed public API, including first-frame-only I2V and first/last-frame FL2V. Examples contain placeholders, not credentials.

## 1. Connection and authentication

**Base URL**

```text
https://ai-studio-h3-jvljvcyoaa-uc.a.run.app
```

| Method | Path | Authentication | Purpose |
|---|---|---|---|
| GET | `/health` | None | Check API process availability |
| POST | `/v2/video_generation` | Client bearer key | Submit an asynchronous generation task |
| GET | `/v2/query/video_generation?task_id=...` | Same client identity | Read task status and output metadata |

Obtain a **client API key** from the service operator through a private channel. Send it as:

```http
Authorization: Bearer <CLIENT_API_KEY>
```

This is an application API key, not a Google OAuth access token or a worker key. A client can query only tasks created under its own identity. Keep the key in a backend secret/environment variable; do not embed it in browser JavaScript, mobile binaries, source control, or URLs. Browser applications should call their own backend, which then calls this API; direct cross-origin browser access is not configured.

Clients communicate only with Cloud Run. They do not connect to the workstation, ComfyUI, Firestore, or `/internal/` worker endpoints.

The API is asynchronous: **submit → persist task ID → poll → retrieve output**. HTTP 200 on submission means accepted, not rendered successfully. No callback, streaming progress, cancellation, task-listing, or direct file-upload endpoint is currently provided.

## 2. Supported generation settings

| Setting | Current contract |
|---|---|
| Model | `MiniMax-H3` |
| I2V | Exactly one `first_frame` image; omit `last_frame` entirely |
| FL2V | Exactly one `first_frame` and one `last_frame` image |
| Prompt | Exactly one nonempty text item; passed to the workflow verbatim |
| Resolution | `768P`, fixed **1344×768** output canvas |
| Ratio | `16:9` only; `adaptive` is no longer accepted |
| Duration | Integer `5` only |
| Output | MP4 with native audio; validated outputs are H.264 video + stereo AAC, 24 fps |
| Actual media length | 124 frames / 24 fps ≈ **5.167 seconds** |
| Scheduling | `realtime` or `batch` |

`16:9` names the source workflow's resolution preset; its alignment produces the exact dimensions 1344×768. Input images do not change the output dimensions. The H3 node stretches the first frame to the canvas and uses aspect-preserving center cropping for the last frame; prepare images accordingly if exact framing matters.

A phrase such as “时长：4s” in the prompt remains text and does not override `duration: 5`. Output is generative; timing, motion, and spoken words are not guaranteed to match every prompt instruction exactly.

Both modes execute the same model/workflow. Workers choose queued realtime tasks before batch tasks, oldest first within each mode. Realtime priority does not interrupt an already running task. Batch waiting time can increase under sustained realtime traffic; there is no queue-wait SLA or promised 41-second generation time.

## 3. Submit a task

```http
POST /v2/video_generation
Content-Type: application/json
Authorization: Bearer <CLIENT_API_KEY>
Idempotency-Key: <UNIQUE_LOGICAL_REQUEST_ID>
```

### Request fields

| Field | Type | Required | Allowed value / behavior |
|---|---|---|---|
| `model` | string | Yes | `MiniMax-H3` |
| `mode` | string | Yes | `realtime` or `batch` |
| `resolution` | string | Yes | `768P` |
| `duration` | integer | Yes | `5` |
| `ratio` | string | Yes | `16:9` |
| `content` | array | Yes | One text item, one first frame, optional last frame |
| `metadata` | object | No | Accepted application metadata; does not affect inference and is not returned by the query endpoint |
| `callback_url` | — | No | Omit; non-null values are rejected |

The entire JSON request must fit in **64 KiB**, including URLs, text, and metadata. Unknown top-level fields are rejected. Do not send a top-level `seed`, width, height, steps, or workflow selector. The service selects and persists the seed internally.

Content item formats:

```json
{"type": "text", "text": "Your complete visual, dialogue, and audio instructions."}
```

```json
{"type": "image_url", "role": "first_frame", "image_url": "https://example.com/first.png"}
```

```json
{"type": "image_url", "role": "last_frame", "image_url": "https://example.com/last.png"}
```

`image_url` is a **string**, not an object containing a `url` property. Image roles are required and case-sensitive. Item order does not choose the role. Only-first, first-plus-last are supported; no images, only-last, duplicate first/last roles, and empty image URLs are rejected.

### Example A — first frame only (I2V)

Save as `request.json`, replacing the example image URL with a reachable image:

```json
{
  "model": "MiniMax-H3",
  "mode": "realtime",
  "resolution": "768P",
  "duration": 5,
  "ratio": "16:9",
  "content": [
    {
      "type": "text",
      "text": "景别：过肩镜头/患者看医生\n运镜：切入，稳定构图\n情绪/动作：女医生抬头看向男患者，进入问诊状态。\n台词：女医生：你这些症状从什么时候开始的？\n音效：环境底噪降低，语音清晰\n时长：4s"
    },
    {
      "type": "image_url",
      "role": "first_frame",
      "image_url": "https://example.com/first.png"
    }
  ]
}
```

Do not add an empty or null last-frame item. The task will report `workflow_type: "i2v_first"` and `usage.input_image_count: 1`.

### Example B — first and last frames (FL2V)

```json
{
  "model": "MiniMax-H3",
  "mode": "realtime",
  "resolution": "768P",
  "duration": 5,
  "ratio": "16:9",
  "content": [
    {"type": "text", "text": "A smooth transition from the opening frame to the final frame, with natural room tone."},
    {"type": "image_url", "role": "first_frame", "image_url": "https://example.com/first.png"},
    {"type": "image_url", "role": "last_frame", "image_url": "https://example.com/last.png"}
  ]
}
```

This reports `workflow_type: "fl2v"` and `usage.input_image_count: 2`. Both roles may use the same URL if the intended start and end frame are identical.

### Input image hosting

Upload images to storage accessible to the worker before submitting. The API does not accept multipart uploads, local paths, base64/data URLs, `gs://` input URLs, or browser login cookies.

- Use a directly downloadable HTTPS image URL, including a GCS signed GET URL for a private object. HTTP on public endpoints is also accepted by the current downloader, but HTTPS is recommended.
- Hosts must resolve exclusively to public IPs. Loopback/private-network addresses and URLs with embedded username/password are rejected; only ports 80/443 are supported. Redirect targets are checked too.
- Each image download is bounded to 20 MiB and 32,000,000 decoded pixels. PNG or JPEG are recommended.
- A URL returning an HTML login page is not an image. In particular, `https://storage.cloud.google.com/...` normally requires interactive authentication and should not be submitted as the download URL.
- Signed URL validity must cover queue waiting and download time, including possible recovery before submission to ComfyUI. Keep the object stable, preferably pin its GCS generation. Do not log signed URLs publicly.
- Image reachability/decoding is checked by the worker after acceptance. HTTP 200 from create does not prove the image will download; failures can appear later in `task.error`.

An operator with signing rights and a service account authorized to read the object can generate a temporary GCS URL, for example:

```bash
gcloud storage sign-url gs://YOUR_BUCKET/first.png \
  --impersonate-service-account=YOUR_SIGNING_SERVICE_ACCOUNT \
  --path-style-url --region=YOUR_BUCKET_LOCATION --duration=2h
```

Use the returned signed URL as `image_url`. A service account's signing permission alone does not give it permission to read the object. Path-style URLs are appropriate for bucket names containing underscores. Do not disable TLS certificate verification.

### Accepted response — HTTP 200

```json
{
  "task_id": "gen_9bc55a0e91664c7ca934f93aae007b13",
  "status": "accepted",
  "mode": "realtime"
}
```

Persist `task_id` immediately. A replayed idempotent create also returns `accepted`, even if that task has already finished; use the query endpoint for current status.

## 4. Query status and retrieve result metadata

```http
GET /v2/query/video_generation?task_id=gen_9bc55a0e91664c7ca934f93aae007b13
Authorization: Bearer <CLIENT_API_KEY>
```

Poll every **2 seconds**, with jitter/backoff on transient failures. Workers' own 1-second polling interval is not a client polling requirement. The endpoint returns HTTP 200 for an existing accessible task, including when generation failed.

| `task.status` | `task.scheduler_state` | Meaning | Client action |
|---|---|---|---|
| `queued` | `queued` | Awaiting a worker | Continue polling |
| `queued` | `leased` | Assigned; preparing inputs | Continue polling |
| `running` | `running` | Executing the workflow | Continue polling |
| `running` | `uploading` | Uploading/finalizing output | Continue polling |
| `succeeded` | `succeeded` | Completed successfully | Persist output metadata |
| `failed` | `failed` | Terminal failure | Inspect `task.error`; do not poll forever |

For the first four rows, continue polling. `scheduler_state` is a coarse stage, not a percent-complete value. Before success, `content` is null. `metrics` is usually null until successful completion; `error` is null unless a failure was recorded.

### Successful response (taken from a verified I2V task)

```json
{
  "task": {
    "id": "gen_9bc55a0e91664c7ca934f93aae007b13",
    "model": "MiniMax-H3",
    "status": "succeeded",
    "created_at": 1788736848,
    "updated_at": 1788736899,
    "content": {
      "gcs_uri": "gs://self_deployed_model_working_dir/generated_video_dir/gen_9bc55a0e91664c7ca934f93aae007b13.mp4",
      "bucket": "self_deployed_model_working_dir",
      "object": "generated_video_dir/gen_9bc55a0e91664c7ca934f93aae007b13.mp4",
      "gcs_generation": "1788736899036690",
      "checksum": {"algorithm": "crc32c", "value": "8aNhdg=="}
    },
    "resolution": "768P",
    "duration": 5,
    "ratio": "16:9",
    "mode": "realtime",
    "workflow_type": "i2v_first",
    "scheduler_state": "succeeded",
    "task_type": "generation",
    "modality": "video",
    "usage": {"input_image_count": 1, "output_seconds": 5},
    "metrics": {
      "inference_time_ms": 48563,
      "queue_time_ms": 2162,
      "upload_time_ms": 0,
      "total_time_ms": 50726
    },
    "error": null
  }
}
```

This is a historical example belonging to the test client; it is not a task that an independently issued client key can necessarily query.

Timestamps are UTC Unix **seconds**; metric durations are **milliseconds**. `queue_time_ms` includes preparation until the first observed running phase, not just queue residence. `inference_time_ms` is execution-stage wall-clock time, not pure GPU sampling time. Short uploads may finish between heartbeats and show zero upload time, with that interval included in execution time. `usage.output_seconds` reflects requested duration, not exact encoded media duration or a pricing statement.

Terminal task records are configured for deletion after 7 days; backend TTL deletion is asynchronous. Persist task/output metadata in your own system. Input and output storage retention is separate. There is no API for listing or searching all previous tasks.

## 5. Download or play the video

**The client API key does not grant GCS read access.** A `gs://` URI is an object locator, not a public playback URL. The current API returns metadata; it does not stream the MP4 or generate a signed output URL.

Before integrating, arrange one of these with the service operator:

1. Your backend identity receives read access to its authorized output objects and downloads them using GCS tooling/SDKs.
2. An authorized backend/operator supplies a short-lived signed GET URL for the result, suitable for your client to download/play.

Do not make the bucket public as part of client setup. A browser-authenticated `storage.cloud.google.com` link may be useful to an authorized operator, but is not an application download API.

Example download with an already authorized Google identity:

```bash
gcloud storage cp \
  'gs://self_deployed_model_working_dir/generated_video_dir/gen_9bc55a0e91664c7ca934f93aae007b13.mp4#1788736899036690' \
  result.mp4
```

Use the `gcs_uri` and generation from **your own response**. Retain `gcs_generation` as a string; do not truncate large generation values through limited-precision number types. Pin the generation when downloading, and verify the base64 CRC32C in `checksum.value` against the downloaded bytes. CRC32C is not CRC32 or SHA-256.

## 6. Idempotency and retries

Send a nonempty `Idempotency-Key` of at most **256 characters** for every create. Generate a new key for a new logical generation, and persist the key **and exact request payload before the first POST**.

- Same client identity + same key + same validated payload returns the original task ID within the 7-day idempotency window.
- Same key with changed payload returns HTTP 409 / `IDEMPOTENCY_CONFLICT`. Changing the prompt, mode, metadata, or signed image URL counts as changing the payload.
- If a POST times out or its response is lost, retry the **same key and payload**. Creating a new key can produce a second video while the first is still running.
- An exhausted HTTP retry budget means the outcome may be unknown, not that no task was created. Preserve the key/payload and recover with the same create request.
- After receiving the task ID, retry the GET query on transient errors; do not resubmit the POST just because rendering takes time.
- Failed tasks are terminal and are not automatically requeued. Replaying their original idempotency key does not rerun inference. An intentional new generation uses a new key, after addressing the failure.
- After the idempotency window, the original key no longer provides a deduplication guarantee. Do not blindly replay old requests.

Application 429/503 responses include `Retry-After: 5`. Honor it and use bounded exponential backoff with jitter for network errors and HTTP 429/500/502/503/504. Gateways may return non-JSON error bodies; branch first on HTTP status. Do not automatically retry permanent 4xx errors unchanged.

Admission limits are soft observations, not queue capacity reservations. Current configured defaults are 20 queued realtime tasks, 200 queued batch tasks, 220 queued total, and 60 new accepted tasks per client per minute. These may change; clients must handle 429 instead of hardcoding these counts. Waiting in the queue has no fixed deadline. Once leased, the current execution deadline is 30 minutes; expired leases/deadlines cause terminal failure rather than automatic transfer to another worker.

## 7. Errors

### HTTP/API error envelope

```json
{
  "type": "error",
  "error": {
    "type": "bad_request_error",
    "code": "INVALID_RATIO_FOR_WORKFLOW",
    "message": "Invalid ratio for workflow",
    "http_code": "400"
  },
  "request_id": "req_0123456789abcdef0123456789abcdef"
}
```

Use `error.code` and the HTTP status for program logic, not message text or `error.type`. `http_code` is a string. Retain `request_id` and `X-Request-ID` when available for support; do not include bearer keys or signed URLs in public logs.

| HTTP | Code | Resolution |
|---|---|---|
| 400 | `INVALID_REQUEST` | Fix malformed/missing fields, empty prompt, or image URL |
| 400 | `UNSUPPORTED_MODEL` | Use `MiniMax-H3` |
| 400 | `INVALID_MODE` | Use `realtime` or `batch` |
| 400 | `UNSUPPORTED_CONTENT_TYPE` / `UNSUPPORTED_CONTENT_ROLE` | Use documented content types and image roles |
| 400 | `UNSUPPORTED_WORKFLOW_COMBINATION` | Supply one first frame and at most one last frame |
| 400 | `UNSUPPORTED_RESOLUTION` / `UNSUPPORTED_DURATION` | Use `768P` and integer `5` |
| 400 | `INVALID_RATIO_FOR_WORKFLOW` | Use `16:9` |
| 400 | `UNSUPPORTED_PARAMETER` | Remove unknown top-level fields / non-null callback URL |
| 401 | `AUTH_FAILED` | Obtain or correct the client key |
| 403 | `FORBIDDEN` | Use a client credential, not a worker credential |
| 404 | `TASK_NOT_FOUND` | Check task ID, original client identity, and retention; not proof that a new submission is needed |
| 409 | `IDEMPOTENCY_CONFLICT` | Recover the original payload/key pairing; use a new key only for an intentional new job |
| 413 | `INVALID_REQUEST` | Reduce the JSON body below 64 KiB; never inline image bytes |
| 429 | `QUEUE_FULL` | Soft queue threshold reached; retry later with the same key/payload |
| 429 | `RATE_LIMITED` | Client admission rate reached; back off |
| 503 | `SERVICE_MAINTENANCE` | Submissions temporarily paused for rollout; retry later |
| 503 | `QUEUE_UNAVAILABLE` | Cloud dependency temporarily unavailable; retry with backoff |
| 500 | `INTERNAL_ERROR` | Retry transiently; contact operator if persistent |

### Generation failure inside an HTTP 200 query response

For a failed task, `task.status` is `failed`, `task.content` is null, and `task.error` contains `code` and `message`, for example:

```json
{"code": "WORKER_LEASE_EXPIRED", "message": "WORKER_LEASE_EXPIRED"}
```

| Task error code | Meaning / next action |
|---|---|
| `INVALID_REQUEST` | Worker could not use input, such as invalid/unreadable image; check URL expiry and image limits |
| `COMFYUI_UNAVAILABLE` | Inference service unavailable; contact operator before a deliberate retry |
| `INFERENCE_FAILED` | Workflow execution or media validation failed |
| `GCS_UPLOAD_FAILED` | Output upload failed |
| `RESULT_VERIFICATION_FAILED` | Cloud could not verify the expected output object |
| `SUBMISSION_UNCERTAIN` | Inference submission may have happened; operator must reconcile before an intentional new generation |
| `WORKER_LEASE_EXPIRED` | Worker stopped renewing its lease |
| `TASK_DEADLINE_EXCEEDED` | Leased task exceeded its execution deadline |

Do not confuse a failed GET transport request with a successfully fetched task whose generation failed.

## 8. curl quick start

Prepare `request.json` from section 3. Set the key privately and generate the idempotency key **once per logical request**; keep it and the same request file for any retry.

```bash
export AI_STUDIO_BASE_URL='https://ai-studio-h3-jvljvcyoaa-uc.a.run.app'
# Supply AI_STUDIO_API_KEY through your secret manager or private shell environment.
export AI_STUDIO_IDEMPOTENCY_KEY="$(python3 -c 'import uuid; print(uuid.uuid4())')"

curl --silent --show-error --fail-with-body \
  --connect-timeout 5 --max-time 35 \
  -X POST "$AI_STUDIO_BASE_URL/v2/video_generation" \
  -H "Authorization: Bearer $AI_STUDIO_API_KEY" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $AI_STUDIO_IDEMPOTENCY_KEY" \
  --data-binary @request.json
```

Copy the returned ID into `TASK_ID`. Do not regenerate the idempotency key when retrying an uncertain POST.

```bash
TASK_ID='gen_REPLACE_WITH_YOUR_RETURNED_ID'

curl --silent --show-error --fail-with-body \
  --connect-timeout 5 --max-time 35 \
  --get "$AI_STUDIO_BASE_URL/v2/query/video_generation" \
  -H "Authorization: Bearer $AI_STUDIO_API_KEY" \
  --data-urlencode "task_id=$TASK_ID"
```

Repeat the GET until `task.status` is `succeeded` or `failed`. Curl examples show individual calls; implement the retry policy above in your application. If an older curl lacks `--fail-with-body`, inspect HTTP status explicitly instead.

## 9. Runnable Python client

Install `requests`, save the code below as `generate_video.py`, and supply the environment variables used by the curl example. Reuse the same `request.json` and persisted idempotency key after a process restart. Alternatively, set `AI_STUDIO_TASK_ID` to resume polling an already accepted task without POSTing again.

```bash
python3 -m pip install requests
python3 generate_video.py
```

```python
import json
import os
import random
import time
from pathlib import Path

import requests

BASE = os.getenv(
    "AI_STUDIO_BASE_URL",
    "https://ai-studio-h3-jvljvcyoaa-uc.a.run.app",
).rstrip("/")
RETRYABLE = {429, 500, 502, 503, 504}


def request_json(session, method, path, **kwargs):
    # POST retries are safe here only because the caller supplies a stable key/payload.
    for attempt in range(8):
        response = None
        try:
            response = session.request(
                method, BASE + path, timeout=(5, 30), allow_redirects=False, **kwargs
            )
        except requests.RequestException:
            if attempt == 7:
                raise RuntimeError(
                    "Network retries exhausted; preserve the task ID or create key/payload."
                ) from None
        else:
            if response.status_code == 200:
                return response.json()
            if response.status_code not in RETRYABLE:
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                code = body.get("error", {}).get("code", "HTTP_ERROR")
                request_id = body.get("request_id") or response.headers.get("X-Request-ID")
                raise RuntimeError(f"HTTP {response.status_code}: {code}; request_id={request_id}")
            if attempt == 7:
                raise RuntimeError(
                    f"HTTP {response.status_code} retries exhausted; preserve submission state."
                )
        delay = min(2 ** attempt, 30)
        if response is not None:
            retry_after = response.headers.get("Retry-After", "")
            if retry_after.isdigit():
                delay = max(delay, int(retry_after))
        time.sleep(delay + random.uniform(0, 1))
    raise RuntimeError("Unreachable")


def main():
    session = requests.Session()
    session.headers["Authorization"] = "Bearer " + os.environ["AI_STUDIO_API_KEY"]
    task_id = os.getenv("AI_STUDIO_TASK_ID")
    if not task_id:
        # The caller persists this key and request file BEFORE the first invocation.
        key = os.environ["AI_STUDIO_IDEMPOTENCY_KEY"]
        if not key or len(key) > 256:
            raise ValueError("Use a nonempty idempotency key of at most 256 characters")
        payload = json.loads(Path(os.getenv("AI_STUDIO_REQUEST_FILE", "request.json")).read_text())
        accepted = request_json(
            session, "POST", "/v2/video_generation",
            headers={"Idempotency-Key": key}, json=payload,
        )
        task_id = accepted["task_id"]
    print(f"Task ID: {task_id}", flush=True)  # Persist in your own job record.

    # Client observation budget, NOT a server-side queue deadline or cancellation.
    deadline = time.monotonic() + float(os.getenv("AI_STUDIO_WAIT_SECONDS", "3600"))
    previous = None
    while time.monotonic() < deadline:
        task = request_json(
            session, "GET", "/v2/query/video_generation", params={"task_id": task_id}
        )["task"]
        state = task["scheduler_state"]
        if state != previous:
            print(f"{task_id}: {state}", flush=True)
            previous = state
        if task["status"] == "succeeded":
            # Save output metadata. Actual download requires separate GCS read access.
            Path(f"{task_id}.result.json").write_text(json.dumps(task, ensure_ascii=False, indent=2))
            print(json.dumps(task["content"], ensure_ascii=False, indent=2))
            return
        if task["status"] == "failed":
            code = (task.get("error") or {}).get("code", "UNKNOWN")
            raise RuntimeError(f"Generation failed: {task_id}; code={code}")
        time.sleep(2 + random.uniform(0, 0.5))
    raise TimeoutError(
        f"Stopped waiting for {task_id}; it may still run. Resume with AI_STUDIO_TASK_ID."
    )


if __name__ == "__main__":
    main()
```

This script submits through **Cloud Run HTTP**, then polls Cloud Run. It never invokes a local runner. In production, persist job IDs, payloads, keys, and output metadata in your application's datastore; use one immutable payload/key pair per logical request and do not log private input URLs.

## 10. Integration checklist

- Obtain a client API key and arrange output-object read access or a signed-output delivery mechanism.
- Upload a test image and confirm its direct download URL works without browser cookies.
- Submit first-frame-only and first/last-frame cases using `768P`, `5`, and `16:9`.
- Persist the idempotency key/payload before POST, then the returned task ID.
- Handle both terminal task statuses, transient HTTP failures, and client-side waiting timeouts.
- Save result generation/checksum and verify the downloaded output.
- Keep task history on the client side if it must outlive the server's terminal-task retention.

Both input cases have been verified end to end through this deployed Cloud Run API on both workstation GPUs. See [deployment and test evidence](H3_INPUTS_E2E_REPORT.md). Those measured runs demonstrate functionality; they are not a latency SLA.

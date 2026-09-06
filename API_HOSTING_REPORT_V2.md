# AI Studio MiniMax H3 API Hosting Report V2

## Host
- Date UTC: 2026-09-04
- Hosting mode: runpod
- GPU: NVIDIA GeForce RTX 5090 (32607 MiB), driver 580.126.09
- OS: Linux 6.8.0-87-generic
- CUDA: cu130 (per PyTorch build below)
- PyTorch: 2.10.0+cu130

## ComfyUI
- Root: /workspace/runpod-slim/ComfyUI
- Python: 3.12.3 (venv `.venv-cu128`)
- Version/commit: 0.30.0 / `004b7753f78f4f6573a0b49aad020657968e4cdc`
- Internal URL: http://127.0.0.1:8188
- Startup method: tmux session `comfyui-sage` (`--listen 0.0.0.0 --port 8188 --enable-cors-header --use-sage-attention`)

## Supported workflows
- MiniMax-H3 T2V: **disabled** — underlying `MiniMaxH3ImageToVideo` node supports it (no images connected) but never tested end-to-end
- MiniMax-H3 I2V first: **disabled** — no dedicated I2V checkpoint has been validated yet (all captured workflows use the FL2V-distilled checkpoint family)
- MiniMax-H3 I2V last: **disabled** — same reason
- MiniMax-H3 FL2V: **enabled and validated** (`workflows/minimax_h3_fl2v_api.json`)
- MiniMax-H3-Max (any mode): not installed
- R2V (reference-to-video): not in scope for this version; no node/checkpoint exists yet, to be added later
- Disabled workflows and reasons: see above; all can be enabled later purely by flipping `enabled: true` in `WORKFLOW_REGISTRY.json` plus a preset entry, since they route through the same `MiniMaxH3ImageToVideo` node — no code changes needed once validated

Note: the four originally-captured workflow files were all mislabeled with `i2v_*` filenames despite using the FL2V-distilled LoRA checkpoint family; they have been renamed to `fl2v_*` in `ComfyUI/user/default/workflows/`.

## Public API
- Create endpoint: `POST /v2/video_generation`
- Query endpoint: `GET /v2/query/video_generation?task_id=...`
- Health endpoint: `GET /healthz` (unauthenticated by design)
- Auth: `Authorization: Bearer <AI_STUDIO_API_KEY>` on create/query; enforced, tested (401 `AUTH_FAILED` on bad/missing key)
- Request schema: MiniMax-V2-style (`model`, `mode`, `content[]`, `resolution`, `duration`, `ratio`, optional `callback_url`/`metadata`); `callback_url` explicitly rejected with `400 UNSUPPORTED_PARAMETER` (not implemented in this baseline)
- Query schema: MiniMax-style `task` object with `gcs_uri`/`bucket`/`object` once succeeded

## Scheduling
- Modes: `realtime`, `batch`
- Dispatch policy: non-preemptive priority — realtime always drains ahead of batch when both are pending; a task already inside ComfyUI is never interrupted
- Max pending realtime: 20
- Max pending batch: 200
- Max total pending: 220
- Max active in ComfyUI: 2 (target: 1 running + 1 prefetched)
- Queue-depth invariant result: **PASS** — observed exactly 1 running + 1 prefetched under concurrent load, never exceeded
- Priority-order test result: **PASS** — with `batch_A` (running), `batch_B` (pending), `realtime_A` (arrives after), `realtime_A` was dispatched into the next free slot ahead of the longer-waiting `batch_B`; `batch_B` was correctly delayed, not starved (it ran and succeeded once a slot freed)

## Workflow routing
- Registry path: `workflows/WORKFLOW_REGISTRY.json`
- T2V workflow file: null (disabled)
- I2V first workflow file: null (disabled)
- I2V last workflow file: null (disabled)
- FL2V workflow file: `minimax_h3_fl2v_api.json`
- Resolution/duration/ratio presets: `workflows/PRESETS.json` — only `768P` / `5s` / `adaptive` are currently exposed, matching what has actually been tested; broadening these is a config-only change

## GCS
- Project: novvy-dev
- Bucket: self_deployed_model_working_dir
- Prefix: generated_video_dir
- Credential method: **service-account impersonation** (`ai-studio-h3-hosting@novvy-dev.iam.gserviceaccount.com`), scoped to `roles/storage.objectAdmin` on this bucket only. No static key file exists — org policy (`constraints/iam.disableServiceAccountKeyCreation`) blocks key creation, so `founders@novvy.ai` was granted `roles/iam.serviceAccountTokenCreator` on the service account instead, and the app mints short-lived tokens via `google.auth.impersonated_credentials` at runtime.
- Example output URI: `gs://self_deployed_model_working_dir/generated_video_dir/gen_2f5aaefe7efb4dec9cab817b626eb45a.mp4` (independently verified via `gcloud storage ls -L`: 3,582,081 bytes, `video/mp4`)

## Validation
- Raw T2V API test: N/A (disabled)
- Raw I2V API test: N/A (disabled); the underlying single-image code path was exercised as part of the FL2V graph-building logic but not tested as a standalone public workflow_type
- Raw FL2V API test: **PASS** — tested directly against ComfyUI's `/prompt` twice: once via the fixed-ratio `ResolutionSelector` path, once via the adaptive image-derived resolution path (the one the public API actually uses). Both produced valid H264/AAC MP4s verified with `ffprobe`.
- Public create/query test: **PASS** — real request through the public API end-to-end (validation → queue → workflow router → graph patch → ComfyUI execution → ffprobe → GCS upload → query returns correct GCS location)
- Restart recovery: **PASS** — killed the API process mid-flight (one job still executing in ComfyUI); on restart, previously-succeeded jobs remained queryable with intact GCS references, and the in-flight job was correctly reconstructed from the job store and finalized (uploaded to GCS) by the new process
- GCS upload verification: **PASS** — confirmed independently via `gcloud storage ls -L` (not just trusting the app's own report)
- Negative-path validation: **PASS** — unsupported model, missing text, invalid ratio for workflow, invalid mode, unsupported duration, bad auth, unknown task_id, and SSRF-guarded private/loopback image URLs all rejected with the documented error codes

## Known limitations / explicitly deferred
- Public hosting (RunPod proxy / Cloudflare Tunnel) is **not yet set up** — deferred by request; service currently reachable only on `127.0.0.1:8000` inside the pod (auth via bearer token is already enforced regardless of network exposure)
- Public status only distinguishes `queued`/`running`(uploading)/`succeeded`/`failed`; the dispatcher does not currently poll ComfyUI's live `queue_running` list to promote `prefetched` → public `running` before completion (plan explicitly allows collapsing this into `queued`)
- `JOB_RETENTION_HOURS` is defined but no cleanup job removes old job files yet
- t2v / i2v_first / i2v_last / r2v are all deferred per user decision, not implementation limitations — the same code path already supports the first three; enabling them is a config change once a checkpoint is validated

## Final status
**PASS** for the scope actually enabled and requested (fl2v, realtime + batch scheduling, GCS upload, restart recovery). Public network exposure intentionally deferred.

The service is running durably in tmux session `ai-studio-api` (log: `/workspace/deployment_logs/ai-studio-api.log`), matching the existing `comfyui-sage` pattern.

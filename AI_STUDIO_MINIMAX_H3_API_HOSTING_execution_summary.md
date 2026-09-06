# AI Studio — MiniMax H3 API Hosting: Execution Summary

**Scope:** Implementation of `AI_STUDIO_MINIMAX_H3_API_HOSTING_PLAN_V2.md` on the RunPod RTX 5090 host.
**Status:** fl2v enabled and validated end-to-end in production-shape (scheduler, GCS upload, restart recovery). t2v/i2v/r2v and public network exposure explicitly deferred (see below).
**Service location:** `/workspace/ai_studio_api_v2`, running in tmux session `ai-studio-api` (log: `/workspace/deployment_logs/ai-studio-api.log`).

---

## 1. Environment discovery (Phase 0)

- RunPod pod `np6behzi50clz2`, RTX 5090 (32GB), driver 580.126.09.
- ComfyUI already running healthy at `/workspace/runpod-slim/ComfyUI` (v0.30.0, commit `004b775`), in tmux session `comfyui-sage`, venv `.venv-cu128`, `--use-sage-attention`.
- ComfyUI is also reachable publicly via RunPod's HTTP proxy at `https://np6behzi50clz2-8188.proxy.runpod.net` — this is how the API-format workflow export (a browser-only ComfyUI feature) was obtained without a local browser session.

## 2. Correcting a workflow-naming assumption (Phase 1)

The plan assumed working `t2v`/`i2v`/`fl2v` ComfyUI workflows already existed as three distinct artifacts. Investigation found:

- All four saved workflows in `ComfyUI/user/default/workflows/` were named `minimax_h3_i2v_*` but actually used the **FL2V-distilled LoRA checkpoint family** (`minimax_h3_fl2v_turbo_*`), not a dedicated I2V checkpoint — confirmed by inspecting each graph's `LoraLoaderModelOnly` node.
- The client corrected this: the files were renamed to `fl2v_*` (`fl2v_lightx2v_turbo_official`, `fl2v_turbo_4step_768p`, `fl2v_turbo_8step`, `fl2v_turbo_baseline`). No real i2v checkpoint exists yet; the client will add one later.
- **Structural discovery:** the entire pipeline is one universal ComfyUI node, `MiniMaxH3ImageToVideo`, with `first_frame` and `last_frame` as *optional* inputs (confirmed via `/object_info`). t2v/i2v_first/i2v_last/fl2v are not four different graphs — they are the same graph with different subsets of optional images wired in. This means enabling t2v/i2v later is a **registry config change, not new code**, once a checkpoint is validated for that mode.
- The captured workflow also revealed no `reference_image`/`reference_video`/`reference_audio` inputs exist on this node — so a future r2v (reference-to-video) capability will require a genuinely new node/checkpoint, not just new request-schema wiring.

## 3. API-format export required browser automation, worked around without one

ComfyUI's "Export (API Format)" — the flattening of a saved graph into the flat `{node_id: {class_type, inputs}}` prompt format required by `/prompt` — only runs client-side in the browser. No headless/CLI equivalent exists in this ComfyUI install (checked: no Node.js, backend "subgraph" execution logic is unrelated to the frontend's static UI grouping, no bundled conversion utility in `comfy-kitchen`/`comfy-aimdo`). Rather than guess a graph-flattening algorithm, the client performed the browser export via ComfyUI's public RunPod proxy URL and handed back the resulting file. The result confirmed ComfyUI's actual ID-namespacing convention for flattened subgraph nodes (`<parent_id>:<child_id>`, e.g. `105:104`), which is now documented for future workflow captures.

## 4. Validation methodology: prove it, don't assume it

Two raw-ComfyUI-API test scripts (`tests/raw_comfy_fl2v_test.py`, `tests/raw_comfy_fl2v_adaptive_test.py`) were written and run against live GPU inference before any FastAPI code was written:

- Fixed-ratio path (ResolutionSelector, 16:9): produced a valid 1344×768 h264/aac MP4.
- **Adaptive-resolution path** (image-derived width/height via `ImageScaleToTotalPixels` + `GetImageSize`) — the *only* ratio mode the public API actually exposes — was separately validated, since it is a different code path from the fixed-ratio one and untested capability must not be claimed as supported.

This caught, before any client-facing code existed, that the "fl2v" label the client uses covers a node that natively supports 0/1/2 optional images — informing the workflow-router design.

## 5. GCS credentials: org policy blocked the plan's assumed approach

The plan's `.env.example` assumes a bucket + project with implicit credentials. In practice:

- Interactive `gsutil`/`gcloud` access required a manual reauthentication step (`gcloud auth login --no-launch-browser --update-adc`) due to org session policy — not suitable for a persistent server.
- Creating a service-account **key file** was attempted and blocked by org policy `constraints/iam.disableServiceAccountKeyCreation`.
- Resolved with **keyless service-account impersonation**: a dedicated service account (`ai-studio-h3-hosting@novvy-dev.iam.gserviceaccount.com`) was created with `roles/storage.objectAdmin` scoped to only `gs://self_deployed_model_working_dir` (bucket-level IAM binding, not project-wide), and `founders@novvy.ai` was granted `roles/iam.serviceAccountTokenCreator` on it. The app (`app/gcs_uploader.py`) mints short-lived tokens at runtime via `google.auth.impersonated_credentials`. No long-lived key ever exists on disk.
- This was smoke-tested independently via `gcloud storage ls --impersonate-service-account=...` before being wired into the app, and every upload in end-to-end testing was independently re-verified via `gcloud storage ls -L` (not just trusting the app's own success report).

## 6. Bugs found and fixed during testing (not in a code-review pass — via actually running the system)

- **Fixed random seed**: the captured workflow template hardcodes `noise_seed: 42`. Left unpatched, every single generated video would have used identical noise. Fixed by randomizing the seed per request (`secrets.randbelow`) in `app/workflow.py`.
- **Misclassified errors**: the dispatcher originally wrapped both request-validation failures (e.g. an image URL that 403s, or resolves to a private IP) and actual ComfyUI submission failures in one `except Exception` block, mislabeling both as `COMFYUI_UNAVAILABLE`. Found via a real test with a Wikipedia image URL that returned HTTP 403 — the error said "ComfyUI unavailable" when ComfyUI was fine. Split into two `try` blocks so validation/build errors keep their real error code (`INVALID_REQUEST`, etc.) and only genuine ComfyUI-layer failures use `COMFYUI_UNAVAILABLE`.
- **Restart-recovery gap**: the in-memory `_in_flight` map (task_id → ComfyUI prompt_id) was empty on process start, meaning a job already submitted to ComfyUI before a restart would be orphaned — job store would show it stuck at `prefetched` forever. Fixed by reconstructing `_in_flight` from the job store at startup for any job in an active state with a recorded `comfy_prompt_id`. This was then verified for real: killed the API process mid-render, restarted it, and confirmed the in-flight job was picked back up and correctly finalized (ffprobe + GCS upload) by the new process.
- **404 on FastAPI's default validation errors**: an invalid `mode` value initially returned Pydantic's raw 422 error shape instead of the plan's required consistent `{"type": "error", "error": {...}}` schema. Added a `RequestValidationError` handler mapping to the documented error codes (`INVALID_MODE`, etc.).
- **`pkill` self-matching**: operationally hit `pkill -f "uvicorn app.main:app"` matching the invoking shell's own command line (since it contained that literal string as script text) and killing the wrong process. Standard workaround applied (`pkill -f "[u]vicorn app.main:app"`) for all subsequent process management.

## 7. What was actually proven end-to-end (not just written)

- A real `POST /v2/video_generation` → `GET /v2/query/video_generation` round trip: validation → priority queue → workflow router → graph patch (adaptive resolution, per-request random seed, SSRF-guarded image download) → ComfyUI execution → ffprobe validation → GCS upload → correct GCS URI returned. Object independently verified in the bucket (3,582,081 bytes, `video/mp4`).
- **Queue-depth invariant**: under 3 concurrent submissions, ComfyUI never held more than 1 running + 1 pending at once.
- **Priority scheduling**: with `batch_A` running and `batch_B` waiting, a `realtime_A` request that arrived after both still got the next free slot ahead of `batch_B` — confirmed via job `scheduler_state`, and `batch_B` was not starved (it completed once a slot freed).
- **Restart recovery**: killed the API process mid-flight; succeeded jobs remained queryable with intact GCS references, and the reconstructed in-flight job correctly finalized under the new process.
- **Negative-path validation**: unsupported model, missing text content, invalid ratio for a workflow type, invalid `mode`, unsupported duration, bad bearer token, unknown `task_id`, and SSRF-guarded private/loopback image URLs — all rejected with the documented error codes.

## 8. Explicitly deferred (client decisions, not implementation gaps)

- **t2v / i2v_first / i2v_last**: disabled in `WORKFLOW_REGISTRY.json` pending a validated checkpoint for each mode. The code path already supports them (same node, same patch logic minus one/two image wirings) — enabling is a config change once tested.
- **r2v**: out of scope; requires a new ComfyUI node/checkpoint that doesn't exist yet.
- **Public network exposure** (RunPod proxy port or Cloudflare Tunnel): deferred by the client to avoid the pod-restart risk of adding a new RunPod exposed port. The bearer-token auth gate (`Authorization: Bearer <AI_STUDIO_API_KEY>`) is already enforced on both `POST /v2/video_generation` and `GET /v2/query/video_generation` regardless of network reachability; only `GET /healthz` is unauthenticated by design.
- `callback_url` is explicitly rejected (`400 UNSUPPORTED_PARAMETER`) — not implemented in this baseline, per plan.
- `JOB_RETENTION_HOURS` is a defined config value but no cleanup job removes old job files yet.
- Public status granularity: `prefetched` and actively-`running` both currently map to the public status `queued` until completion (the plan explicitly permits this collapse).

## 9. Full engineering detail

See `API_HOSTING_REPORT_V2.md` in `/workspace/ai_studio_api_v2` for the field-by-field deployment report (host specs, exact commit hashes, preset values, GCS credential chain, per-test results).

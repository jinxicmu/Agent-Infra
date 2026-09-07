# Local dual-GPU deployment

> 最新参数能力与部署见 [H3_PARAMETERS_REPORT.md](H3_PARAMETERS_REPORT.md)；本文件保留之前版本的验证记录。

> Current workflow/API update: first-frame I2V and first/last-frame FL2V are deployed and validated. See [current deployment and E2E report](H3_INPUTS_E2E_REPORT.md). The details below record the initial deployment.

Deployed September 6, 2026, in GCP project `novvy-dev` and region `us-central1`.

## Service and resources

- API base URL: **https://ai-studio-h3-jvljvcyoaa-uc.a.run.app**
- Public liveness: `GET /health` (verified HTTP 200).
- Create: `POST /v2/video_generation`; query: `GET /v2/query/video_generation?task_id=...`.
- Cloud Run service: `ai-studio-h3`, revision `ai-studio-h3-00002-7h4`.
- Image: `us-central1-docker.pkg.dev/novvy-dev/cloud-run-source-deploy/ai-studio-h3@sha256:c7323da3869606b2aa347dce604fe6968c9d70237ec07df06bb7cdb25cfe3b15`.
- Dedicated Firestore database: `ai-studio-h3`, Native mode, `us-central1`. All three task-query indexes are ready. TTL is active for terminal task and idempotency expiration fields.
- Runtime account: `ai-studio-h3-api@novvy-dev.iam.gserviceaccount.com`, with access to the dedicated database, output-object reads, and the two specific API-key secrets.
- Scheduler: `ai-studio-h3-expire-leases`, every minute, verified OIDC caller `ai-studio-h3-scheduler@novvy-dev.iam.gserviceaccount.com`. Audience is the service URL.
- Upload account: `ai-studio-h3-local@novvy-dev.iam.gserviceaccount.com`, with create/read access restricted to `generated_video_dir/` in the output bucket. It cannot overwrite/delete videos or access Firestore.

## Workstation services

All four user-systemd services are installed and enabled: `comfyui@0`, `comfyui@1`, `pull-worker@0`, `pull-worker@1`. User lingering is enabled so they can run without an interactive login and start at boot. Each worker polls once per second and leases one whole task, with no prefetch or cross-GPU sharing.

| Worker | GPU UUID | ComfyUI address |
| --- | --- | --- |
| `local-5090-0` | `GPU-0c1a5b76-724c-4f97-1dca-9eb6bbebdd61` | `127.0.0.1:8188` |
| `local-5090-1` | `GPU-5363b860-acbd-f684-72c2-59123c9d6405` | `127.0.0.1:8189` |

Both processes see exactly one CUDA device. During concurrent inference, each used approximately 27 GB VRAM. The existing CUDA 13.2/SageAttention environment and model files were reused. ComfyUI binds only to loopback; local pull workers expose no HTTP listener.

Private configuration is under `/home/kakarot/.config/agent-infra/`:

- `client-keys.json`: the `ai-studio` client bearer credential; mode 0600.
- `worker-keys.json`: distinct worker bearer credentials; mode 0600.
- `worker-0.env`, `worker-1.env`: installed per-GPU environment files; mode 0600.
- `service-url`: the deployed endpoint.

Actual secret values are not included in repository files or this report. Secret Manager holds `ai-studio-h3-client-keys` and `ai-studio-h3-worker-keys`.

Uploads use `GCS_AUTH_MODE=gcloud`: the existing `founders@novvy.ai` CLI login impersonates the dedicated uploader account and refreshes short-lived credentials. No service-account key or copied refresh-token file was created. This credential source remains subject to the organization's user-session reauthentication policy; a revoked/expired source login requires reauthentication. Standard ADC/workload identity is also supported for a future unattended identity source.

## End-to-end evidence

Two distinct five-second FL2V requests using Google's public scones sample image ran concurrently on the two GPUs. Both completed successfully, passed ffprobe validation, uploaded to GCS, and returned successful task queries. The GCS generations, checksums and object sizes were independently verified. Both MP4s contain H.264 video at 1248×832, AAC audio, and 5.167 seconds of media, independently confirmed with ffprobe.

| Worker | Task ID | MP4 bytes | Observed inference time |
| --- | --- | ---: | ---: |
| `local-5090-0` | `gen_c33197bde051484d89e68e2a48a096e5` | 2,628,668 | 73.07 s |
| `local-5090-1` | `gen_e6bd4c0dfd474513b1593a6aefdd2690` | 3,914,064 | 74.33 s |

Outputs:

- `gs://self_deployed_model_working_dir/generated_video_dir/gen_e6bd4c0dfd474513b1593a6aefdd2690.mp4` — generation `1788686728446932`, CRC32C `/3Gf4g==`.
- `gs://self_deployed_model_working_dir/generated_video_dir/gen_c33197bde051484d89e68e2a48a096e5.mp4` — generation `1788686728156220`, CRC32C `0IH6Ew==`.

The initial queue times include index provisioning during deployment; they are not steady-state scheduling benchmarks. Inference timing is observed through worker phase heartbeats.

A controlled SIGKILL of worker 0 tested real restart recovery while ComfyUI continued independently. Systemd restarted it, the Worker API bound a new session, and the task retained its original ComfyUI prompt ID. It completed successfully without a second submission. Both ComfyUI queues drained to zero running and zero pending.

The scheduled maintenance endpoint returned HTTP 200 after correcting its token audience. With both workers stopped, synthetic task `gen_78aa919e95b049db880697ba6cc63410` was leased without rendering. After its actual 120-second lease elapsed, the authenticated cloud sweep marked it `failed` with `WORKER_LEASE_EXPIRED`; it was never reassigned. Both workers were restarted afterwards. Evidence is in `runtime/deployment-validation/expiry-probe.json`. Post-deployment automated tests: **32 passed**, covering Firestore races, session recovery, worker retries, input/output validation and the gcloud credential adapter.

## Deployment adjustments

Google's frontend intercepted the original `/healthz` request with a 404 before it reached the container. `/health` was added and publicly verified. `/healthz` remains a local/container alias. See [Cloud Run known issues](https://docs.cloud.google.com/run/docs/known-issues).

Scheduler initially used an arbitrary audience; the deployed configuration uses the actual service URL and both the platform and application verify the caller. See [Cloud Run service authentication](https://docs.cloud.google.com/run/docs/authenticating/service-to-service).

No other existing Cloud Run service or existing RunPod application was redeployed. The new Firestore database and service identities are dedicated to this deployment. Source changes remain local; no GitHub push was performed.

## Operations

```bash
systemctl --user status comfyui@0 comfyui@1 pull-worker@0 pull-worker@1
journalctl --user -u pull-worker@0 -u pull-worker@1 --since '10 minutes ago'
```

To stop new work gracefully, stop the two `pull-worker@` units; they finish the current task before exiting within the configured deadline. Preserve worker journals when troubleshooting. Do not run the original externally bound ComfyUI launcher alongside these units. The client API requires the client bearer credential on create/query; worker credentials are not valid client credentials.

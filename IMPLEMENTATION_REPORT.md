# Cloud Run and local worker implementation

Date: September 6, 2026. Implements the approved V2.3 architecture and the subsequent one-second polling change.

## Implemented

- `cloudrun/`: separate Public and Worker API routers; Firestore task-field queue membership; realtime/FIFO transactional claims; per-worker assignment guard; fixed task seed and workflow revision; client-scoped creation idempotency; soft admission thresholds and separate per-client rate records.
- Task/session/token checks on mutations; one-second worker heartbeats; 120-second leases and a 30-minute hard execution deadline; expiry sweep; expired recovery commits failure before returning 409. No automatic task redispatch.
- Explicit `/internal/workers/recover` with journal proof, atomic session rebinding, old-session fencing and identical retry handling. Terminal completion/failure acknowledgements are idempotent.
- `worker/`: outbound-only runtime, independent ComfyUI client, atomic/fsynced journal and local lock, persisted submission/recovery intent, lost-response reconciliation, one active task and no prefetch, bounded input/media handling, create-only GCS uploads, result outbox and local cleanup.
- Per-worker image directories, DNS-pinned public image fetching, loopback-only ComfyUI transport, fixed graph seed, and manifest hash checks. The enabled graph remains FL2V/768P/five seconds/adaptive.
- Cloud-side output verification checks expected object, task/lease metadata, size, media type, CRC32C and GCS generation before success. Public queries do not expose ownership credentials.
- Container definition, Firestore indexes/TTL configuration, cloud deployment script, two UUID-specific environment examples, ComfyUI launcher, user systemd templates and rollout documentation.

The legacy `app/` implementation and its dependencies are unchanged. The new production packages do not import it or each other. Workers have no Firestore dependency; the cloud image contains no worker code, GPU stack or workflow execution graphs.

## Validation

- 29 tests passed using Firestore emulator v1.19.8 and local worker tests. Coverage includes two workers competing for one task, two concurrent tasks, duplicated same-worker claims, priority/FIFO, concurrent creation idempotency, recovery/heartbeat races, expired recovery, absolute deadline, terminal retries, stale result rejection and lease sweeping.
- Worker tests cover lost claim/recovery/completion responses, journal locking, restart with a known prompt, uncertain submission without resubmission, lease deadline enforcement, output-path containment, image SSRF rejection, deterministic graph construction and create-only upload/checksum behavior.
- A synthetic end-to-end test uses the real Worker API JSON transport adapter, FastAPI routes, Firestore transactions, worker lifecycle and real ffprobe validation of a generated sample MP4. ComfyUI rendering and GCS storage are simulated in that test; it is not a real MiniMax render or cloud deployment.
- Cloud Run Docker image built successfully and passed an offline import/isolation smoke check. A separate worker import check confirmed no cloud API, Firestore or FastAPI imports. Shell launcher/deployment syntax and user-systemd unit definitions passed validation.
- Both physical GPUs were checked concurrently with the existing ComfyUI Python environment. Each process saw exactly one RTX 5090 under UUID masking, and each executed a CUDA matrix multiplication successfully with CUDA 13.2.

| Worker | Physical GPU UUID |
| --- | --- |
| `local-5090-0` | `GPU-0c1a5b76-724c-4f97-1dca-9eb6bbebdd61` |
| `local-5090-1` | `GPU-5363b860-acbd-f684-72c2-59123c9d6405` |

## Deployment status

The deployment is now live. See [the deployment report](DEPLOYMENT_REPORT_LOCAL.md) for the endpoint, resource identities, local service configuration, real dual-GPU results and restart-recovery evidence. Post-deployment automated tests pass (32 tests).

The initial implementation was validated before any cloud deployment. Subsequent deployment added the `/health` alias for Cloud Run and explicit gcloud-based keyless upload credentials for this workstation. Source changes have not been pushed to GitHub.

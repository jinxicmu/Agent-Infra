# Local worker rollout

Each process leases one whole task. Neither worker starts an HTTP server. ComfyUI is loopback-only, with isolated CUDA visibility and input/output/temp/user/state directories. Models and the existing CUDA 13.2/SageAttention environment remain shared on disk.

The example GPU UUIDs were read from this workstation. Recheck them with `nvidia-smi --query-gpu=index,uuid,name --format=csv` before installing. Use UUIDs, not mutable GPU indices. Never configure both examples with the same UUID, port, state directory or worker identity.

1. Install worker dependencies into the repository virtual environment, separately from the existing ComfyUI environment: `.venv/bin/pip install -r worker/requirements.txt`. Install `ffprobe` if absent.
2. Deploy and validate the cloud service and indexes first. Copy `worker-0.env.example` and `worker-1.env.example` to `~/.config/agent-infra/worker-0.env` and `worker-1.env`, permissions 0600. Fill in the actual HTTPS URL and distinct worker secrets. These files use systemd environment syntax; do not use shell substitutions inside them.
3. Validate keyless upload credentials. This workstation uses `GCS_AUTH_MODE=gcloud` with the explicitly selected `GCLOUD_ACCOUNT` and uploader service account; Python refreshes short-lived impersonated credentials through the existing gcloud login. `GCS_AUTH_MODE=adc` remains available for standard ADC/workload identity. The CLI's login is not automatically a Python ADC file. Configure `GOOGLE_APPLICATION_CREDENTIALS` only if using an approved external-account/workload-identity configuration; do not introduce service-account keys.
4. Drain any existing ComfyUI or RunPod/local API processes. The old workspace launcher listens on `0.0.0.0` and must not run alongside this deployment. Check GPU memory and ports before startup. Do not kill unrelated GPU jobs.
5. Copy `comfyui@.service` and `pull-worker@.service` into `~/.config/systemd/user/`, adjust repo paths if needed, and run `systemctl --user daemon-reload`.
6. Start only `comfyui@0` and `comfyui@1` initially. Verify `127.0.0.1:8188` and `127.0.0.1:8189`, healthy `/system_stats`, one visible CUDA device per instance, correct UUID-to-process mapping, and empty queues. Do not enable LAN/public listeners or CORS exposure.
7. Start `pull-worker@0` and `pull-worker@1` for controlled end-to-end tests. They refuse a claim while unjournaled work remains in their dedicated ComfyUI. Idle requests and active heartbeats default to one second; no prefetch is performed.
8. After two real independent FL2V tasks succeed concurrently and failure/restart tests pass, enable both pairs of user units. If persistence without login is required, configure user lingering deliberately. No service is installed or enabled by this repository automatically.

Use `journalctl --user -u pull-worker@0 -u pull-worker@1` for logs. SIGTERM stops new claims and allows the current task to finish within its deadline. Unexpected exits preserve `active.json`; keep it during recovery. It contains a lease credential and must remain private. The worker writes recovery intent before transferring sessions, and retries the exact intent after a lost response.

Do not delete a journal to fix a stuck task. A missing journal with an active cloud assignment requires operator reconciliation; a new process cannot silently take over that session. A lost or expired lease drains only the corresponding dedicated ComfyUI, then confirms the terminal cloud outcome. No task transfers to the other GPU.

Local `gen_*` inputs/outputs older than 24 hours are cleaned only when not associated with the current journal. State and credentials remain separate. New claims require 5 GiB free output space. GCS outputs are not deleted automatically. Monitor local disk, GPU health, queue age and repeated authentication failures.

Rollback: stop new local claims, let current jobs drain or explicitly fail, then restore the chosen previous deployment. Never operate the RunPod dispatcher and local workers against the same pending tasks.

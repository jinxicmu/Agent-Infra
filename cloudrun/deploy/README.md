# Cloud deployment

The active design is `AI_STUDIO_MINIMAX_H3_API_HOSTING_PLAN_V2.md`. This directory does not deploy on import or test execution.

Use explicit `--project novvy-dev` on every administrative command; this workstation's default gcloud project may be unrelated. First inspect the existing Firestore database and GCS bucket location, then select a nearby Cloud Run region. Do not create or reset a database implicitly.

Provision these resources in a staging environment before production:

- Enable Cloud Run, Artifact Registry, Firestore, Secret Manager, Cloud Scheduler, and IAM Credentials APIs.
- Create a dedicated Cloud Run runtime service account. Grant `roles/datastore.user` on the selected project/database as appropriate, output-bucket `roles/storage.objectViewer`, and `roles/secretmanager.secretAccessor` on the two specific API-key secrets.
- Create a separate Scheduler caller service account. Preserve the Google-managed Cloud Scheduler service-agent role; the deployer needs permission to act as the caller account. The application checks Scheduler OIDC audience, verified email and exact caller identity.
- Create client and worker API-key secrets as JSON maps: `{"client-id":"<random secret of 32+ characters>"}` and `{"local-5090-0":"<distinct secret>","local-5090-1":"<distinct secret>"}`. Keep actual values out of source, logs, and shell command arguments. Add versions from restricted files using `gcloud secrets versions add ... --data-file=...`.
- Give the worker upload service account `roles/storage.objectCreator` and `roles/storage.objectViewer` on the output bucket (prefer conditions restricting access to `generated_video_dir/`). Workers need object get/create but no overwrite/delete or Firestore access. Authorize the workstation's approved keyless ADC identity to impersonate that account. Validate ADC refresh unattended; interactive gcloud login alone is not ADC.
- Apply `firestore.indexes.json` with Firebase CLI to the selected database, or create equivalent composite indexes with `gcloud firestore indexes composite create --project ... --database ...`. Wait for indexes to finish building. Enable TTL for `tasks.expires_at` and `idempotency.expires_at`; pending/active tasks intentionally have no TTL. The emulator does not prove production index readiness or IAM correctness.

Build from the repository root:

```bash
docker build -f cloudrun/Dockerfile -t YOUR_ARTIFACT_REGISTRY_IMAGE .
docker push YOUR_ARTIFACT_REGISTRY_IMAGE
```

Set the required environment variables listed in `deploy.sh` and run it from the repo root. The script expects an existing database, identities, secrets and indexes. It deploys one service containing both routers and creates/updates the expiry sweep. Prefer an image digest for repeatable rollout. It does not change workstation processes.

Public reachability is intentional; business routes require application bearer auth, and maintenance requires verified Scheduler OIDC. If organization policy blocks unauthenticated Cloud Run invocation, stop and configure the documented additional platform ID-token transport for clients/workers before deployment; the baseline worker does not implement that variant.

Verify `/health`, bad-key rejection, create/query, both worker claims, verified artifact publication, Scheduler execution, and lease expiry in staging. Then connect local workers. A healthy Cloud Run liveness endpoint does not mean GPUs are available.

Queue limits are soft observations, not a hard global capacity lock. API creates additionally use a per-client, per-minute admission record (60 new tasks/minute by default). Exact idempotent retries do not consume that quota. Monitor task age and Firestore contention/read/write volume; continuously active workers produce roughly 172,800 Worker API requests/day combined at a one-second interval.

Use the deployed Cloud Run service URL as the Scheduler OIDC audience. The initial arbitrary audience was rejected by the Cloud Run frontend during rollout. Public `/healthz` is also intercepted by that frontend; `/health` is the externally verified liveness endpoint.

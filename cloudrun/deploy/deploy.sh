#!/usr/bin/env bash
# Explicit staging/production deployment. Secrets, accounts, database and indexes must exist.
set -euo pipefail
: "${GCP_PROJECT:=novvy-dev}"
: "${REGION:?Set the region after checking Firestore and bucket locations}"
: "${IMAGE:?Set the built Cloud Run image digest or immutable tag}"
: "${SERVICE:=ai-studio-h3}"
: "${FIRESTORE_DATABASE:=(default)}"
: "${RUNTIME_SERVICE_ACCOUNT:?Set the Cloud Run runtime service account}"
: "${SCHEDULER_SERVICE_ACCOUNT:?Set the Cloud Scheduler caller service account}"
: "${SCHEDULER_AUDIENCE:?Set the Cloud Run service URL as the OIDC audience}"
: "${CLIENT_KEYS_SECRET:?Set the Secret Manager secret containing client ID to key JSON}"
: "${WORKER_KEYS_SECRET:?Set the Secret Manager secret containing worker ID to key JSON}"
gcloud run deploy "$SERVICE" --project "$GCP_PROJECT" --region "$REGION" \
  --image "$IMAGE" --service-account "$RUNTIME_SERVICE_ACCOUNT" \
  --allow-unauthenticated --cpu 1 --memory 512Mi --min-instances 1 --max-instances 2 \
  --concurrency 20 --timeout 60 \
  --set-env-vars "GCP_PROJECT=$GCP_PROJECT,FIRESTORE_DATABASE=$FIRESTORE_DATABASE,SCHEDULER_SERVICE_ACCOUNT=$SCHEDULER_SERVICE_ACCOUNT,SCHEDULER_AUDIENCE=$SCHEDULER_AUDIENCE" \
  --set-secrets "CLIENT_API_KEYS_JSON=$CLIENT_KEYS_SECRET:latest,WORKER_API_KEYS_JSON=$WORKER_KEYS_SECRET:latest"
service_url=$(gcloud run services describe "$SERVICE" --project "$GCP_PROJECT" --region "$REGION" --format='value(status.url)')
if gcloud scheduler jobs describe "$SERVICE-expire-leases" --project "$GCP_PROJECT" --location "$REGION" >/dev/null 2>&1; then
  scheduler_action=update
else
  scheduler_action=create
fi
gcloud scheduler jobs "$scheduler_action" http "$SERVICE-expire-leases" \
  --project "$GCP_PROJECT" --location "$REGION" --schedule '* * * * *' \
  --uri "$service_url/internal/maintenance/expire-leases" --http-method POST \
  --oidc-service-account-email "$SCHEDULER_SERVICE_ACCOUNT" \
  --oidc-token-audience "$SCHEDULER_AUDIENCE"

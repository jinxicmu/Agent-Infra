# Agent-Infra

The new local hosting implementation separates `cloudrun/` (public API, Worker API and Firestore task ownership) from `worker/` (one outbound-only worker per RTX 5090). The existing `app/` is the RunPod implementation and is not imported by either new package.

**Supports first-frame I2V, first/last-frame FL2V, and Ref2VA with 1–9 reference images and native audio.** See the [complete client integration guide](API_CLIENT_GUIDE.md), [中文 API 示例](API_USAGE_H3.md) and [workflow changes](H3_WORKFLOW_UPDATE.md).

The approved design is [the active V2 plan](AI_STUDIO_MINIMAX_H3_API_HOSTING_PLAN_V2.md). The original RunPod plan is historical reference only.

- [Cloud deployment](cloudrun/deploy/README.md)
- [Local GPU worker rollout](worker/deploy/README.md)
- [Ref2VA 接入与验证](REF2VA_REPORT.md)
- [Validation report](IMPLEMENTATION_REPORT.md)
- [Live deployment report](DEPLOYMENT_REPORT_LOCAL.md)
- [本地监控面板设计（中文，尚未实现）](MONITOR_DASHBOARD_DESIGN_ZH.md)

Live API: **https://ai-studio-h3-jvljvcyoaa-uc.a.run.app**. Liveness is `GET /health`; create/query require the client bearer credential stored in the private workstation configuration.

Public API remains `POST /v2/video_generation` and `GET /v2/query/video_generation?task_id=...`. Supported inputs are MiniMax-H3 first-frame I2V and first/last-frame FL2V, configurable `480P`/`544P`/`720P`/`768P` tiers, 1–15 seconds, explicit aspect ratios or `adaptive` (defaults: `768P`, 5 seconds, `16:9`). I2V/FL2V requires text and one first-frame URL; the last-frame URL is optional. Ref2VA uses text plus 1–9 reference-image URLs and defaults to `544P / 16:9 / 5s`. Create returns a task ID; clients poll the cloud for completion. Workers poll every one second, lease one task, and never prefetch.

## Tests

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
# Start Google's Firestore emulator separately on loopback port 8787.
FIRESTORE_EMULATOR_HOST=127.0.0.1:8787 .venv/bin/python -m pytest
```

Database tests use only emulator project `demo-agent-infra` and clear that project's test collections before each test. They skip when the emulator variable is absent. Never point that variable at a production endpoint. Worker tests simulate ComfyUI/GCS failures without rendering or uploading production objects.

The workflow manifest binds the approved graph/registry/preset hashes to a revision. Intentional workflow changes require regenerating its hashes/revision and coordinated cloud/worker rollout. Workers reject modified artifacts. Do not enable unvalidated models or workflows merely by changing the manifest.

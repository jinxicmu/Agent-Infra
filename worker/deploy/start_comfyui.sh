#!/usr/bin/env bash
set -euo pipefail
: "${COMFY_ROOT:?Set the existing ComfyUI installation path}"
: "${GPU_UUID:?Set the physical GPU UUID}"
: "${COMFY_PORT:?Set the dedicated loopback port}"
: "${COMFY_INPUT_DIR:?Set the worker input directory}"
: "${COMFY_OUTPUT_DIR:?Set the worker output directory}"
: "${WORKER_STATE_DIR:?Set the worker state directory}"
: "${COMFY_PYTHON:=$COMFY_ROOT/venv/bin/python}"
[[ "$GPU_UUID" == GPU-* && "$COMFY_PORT" =~ ^[0-9]+$ ]] || exit 2
(( COMFY_PORT >= 1024 && COMFY_PORT <= 65535 )) || exit 2
export CUDA_VISIBLE_DEVICES="$GPU_UUID"
export PIP_CONSTRAINT="${PIP_CONSTRAINT:-/home/kakarot/Documents/NOVVY/self_deployed_AI_studio/cuda132-constraints.txt}"
export UV_CONSTRAINT="$PIP_CONSTRAINT"
mkdir -p "$COMFY_INPUT_DIR" "$COMFY_OUTPUT_DIR" "$WORKER_STATE_DIR/temp" "$WORKER_STATE_DIR/user"
exec 9>"$WORKER_STATE_DIR/comfy.lock"
flock -n 9
"$COMFY_PYTHON" - <<'PY'
import torch
assert torch.cuda.is_available() and torch.cuda.device_count() == 1, 'Expose exactly one GPU'
assert torch.version.cuda == '13.2', 'Use the validated CUDA 13.2 runtime'
print('GPU:', torch.cuda.get_device_name(0), flush=True)
PY
cd "$COMFY_ROOT"
exec "$COMFY_PYTHON" main.py --listen 127.0.0.1 --port "$COMFY_PORT" \
  --input-directory "$COMFY_INPUT_DIR" --output-directory "$COMFY_OUTPUT_DIR" \
  --temp-directory "$WORKER_STATE_DIR/temp" --user-directory "$WORKER_STATE_DIR/user" \
  --disable-auto-launch --use-sage-attention

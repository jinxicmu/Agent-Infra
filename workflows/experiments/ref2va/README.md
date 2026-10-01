# Experimental Ref2VA comparison

These editable ComfyUI workflows document the earlier comparison against the
LightX2V four-step baseline. LightX2V 8-step is the Ref2VA API
default in the promoted manifest; PAI PDD 8-step and Singularity with LightX2V 4-step remain comparison
workflows. The benchmark results remain historical single-sample evidence.

See [measured results and generated videos](RESULTS.md) for the local comparison.

| ID | Base checkpoint | Acceleration | Steps | Video/audio shift |
| --- | --- | --- | --- | --- |
| `baseline` | Existing Comfy-Org pruned INT8 Ref2VA | Existing LightX2V v0.1 | 4 | 12 / 3 |
| `lightx2v_8step` | Same as baseline | LightX2V Ref2V v1.0 768p | 8 | 12 / 3 |
| `pai_8step` | Same as baseline | Alibaba PAI Ref2VA PDD | 8 | 12 / 3 |
| `singularity_4step` | Singularity Ref2VA pruned v1.3 INT8 | Existing LightX2V v0.1 | 4 | 12 / 3 |

Singularity uses the exact checkpoint requested by the user and its recommended
four-step LoRA, not an eight-step adapter. The LightX2V Ref2V eight-step file is
available but its publisher's model-spec table still documents only Ref2V v0.1;
this comparison retains the existing Ref2VA shift 12/3 and `match` reference
sizing as an explicit experimental assumption. It does not borrow FL2VA's 6/3
settings. All candidates use Euler, single-forward guidance, native audio,
768P portrait, the original three references in order, and seed 42.

## Sources and pinned artifacts

- [LightX2V Ref2V 8-step checkpoint](https://huggingface.co/lightx2v/Minimax-h3-Turbo/blob/main/minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors)
- [LightX2V model specifications](https://github.com/ModelTC/Minimax-H3-Turbo#1-model-specs)
- [Alibaba PAI official release](https://huggingface.co/alibaba-pai/MiniMax-H3-Acc-LoRAs)
- [Singularity exact checkpoint](https://huggingface.co/WarmBloodAban/Minimax-h3_Singularity/blob/main/Minimax-h3_Singularity_ref2va_Pruned_v1.3_int8.safetensors)
- [PDD ComfyUI adapter](https://github.com/Jalen-Brunson/ComfyUI-MiniMax-H3-PDD-Acc)

`models.json` records immutable download revisions, SHA-256 values, byte sizes,
and the PDD custom-node revision. Weights stay in the local ComfyUI model tree.
The model download helper checks an existing file rather than overwriting it:

```bash
.venv/bin/python -m worker.deploy.download_ref2va_experiments /path/to/ComfyUI/models
```

PAI is not a drop-in standard LoRA. `MiniMaxH3PDDAccApply` loads its trunk updates,
rebases AdaLN updates onto the pruned model's curve basis, applies the complete
video/audio output-head banks, and emits the exact eight-step sigma schedule.
The workflow connects that schedule directly to `SamplerCustomAdvanced` and
removes the LightX2V LoRA and `BasicScheduler`. It keeps adapter/head strengths at
1.0 and mismatch/off-grid checks enabled.

To reproduce the adapter installation, clone its repository under
`ComfyUI/custom_nodes/ComfyUI-MiniMax-H3-PDD-Acc` and check out the exact
`custom_node.revision` from `models.json`. Restart the reserved ComfyUI instance
after its queue drains. This adapter needs the bundled `adaln_basis` and
`partition_fingerprints` directories as well as its Python files.

## Editable workflow library

From the Agent-Infra repository root:

```bash
.venv/bin/python -m workflows.ref2va_experiments \
  --user-dir /path/to/comfy-user-directory \
  --input-dir /path/to/comfy-input-directory
```

This generates the three frontend `.json` files and internal `.api.json`
templates, then installs frontend entries under **Workflows → Agent-Infra →
Experimental Ref2VA**, with the six email images. The installer refuses to
overwrite changed library files or input images. Without directory arguments,
it only regenerates the repository artifacts.

Frontend entries open with case 1: 4 seconds, 768P, 9:16, fixed seed 42. To use
case 2, replace the prompt with `tests/fixtures/h3_email_cases/case_2/prompt.txt`,
set duration to 15, and select `h3_case_2_picture_1.png` through
`h3_case_2_picture_3.png`. API templates still need prompt and reference binding;
they are not standalone API requests.

## Tests and real GPU measurements

```bash
# CPU-only contract checks: 2 cases × 4 variants.
.venv/bin/python -m pytest worker/tests/test_h3_email_cases.py -q

# Reserve GPU 0. Stop waits for its current API task to finish.
systemctl --user stop pull-worker@0

# Confirm that port 8188's queue is empty before running.
H3_BENCHMARK_URL=http://127.0.0.1:8188 \
H3_BENCHMARK_GPU=0 \
H3_BENCHMARK_INPUT_DIR="$PWD/runtime/worker-0/input" \
H3_BENCHMARK_OUTPUT_DIR="$PWD/runtime/ref2va-benchmarks" \
.venv/bin/python -m pytest worker/tests/test_h3_email_cases.py -k live -q -s

# After confirming the benchmark queue has finished:
systemctl --user start pull-worker@0
```

`H3_BENCHMARK_VARIANTS` optionally selects comma-separated IDs. GPU tests are
skipped unless `H3_BENCHMARK_URL` is set. They check that the selected GPU's
pull-worker is inactive and that ComfyUI's queue is empty. If a run times out,
leave the worker stopped and inspect the recorded prompt ID before resuming it;
the harness never interrupts unrelated jobs or clears queues.

Each run writes its exact graph, history, sampled GPU memory/utilization,
`result.json`, and MP4 under a unique evidence directory. It rejects a cached
sampler output and validates video dimensions, frame count, frame rate, duration,
and the presence of audio. An unchanged rerun can hit ComfyUI's node cache;
clear the model/node cache through ComfyUI while the reserved queue is idle
before repeating the same case and seed.

Timing is whole ComfyUI execution, including model loading, encoding, sampling,
and decoding. Cached encoders and weights can affect the result; one run per
combination is a smoke benchmark, not a statistically stable speed ranking.
`sampled_peak_vram_mib` is sampled device memory, not an allocator high-water mark.
Visual fidelity, exact dialogue, first-frame similarity, and overlay accuracy
require the separate acceptance checks in the email-fixture README. A passing
media contract does not establish those quality results.

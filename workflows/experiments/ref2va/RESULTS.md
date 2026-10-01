# Ref2VA comparison — 2026-10-01

All eight local GPU runs completed and passed media-contract checks. These are single-run measurements, not a statistically stable speed ranking. The user selected LightX2V eight-step for promotion after reviewing these results; the selection does not establish a speed improvement.

The Singularity workflow uses `Minimax-h3_Singularity_ref2va_Pruned_v1.3_int8.safetensors` with the existing recommended LightX2V four-step LoRA.

## Measured execution

Whole ComfyUI execution in seconds, including model loading, encoding, sampling, and decoding. GPU 0: NVIDIA RTX 5090, 32 GB. Seed 42, original email prompts and three references, 768P portrait, native audio. GPU 1 remained available to serve the existing API; host memory and model/encoder caches were not reset between all runs.

| Variant | Case 1 (4s request) | Case 2 (15s request) | Peak sampled VRAM, case 1 / 2 |
| --- | ---: | ---: | ---: |
| `baseline` | 59.912s | 211.548s | 27,967 / 32,091 MiB |
| `lightx2v_8step` | 70.081s | 362.945s | 31,869 / 30,933 MiB |
| `pai_8step` | 78.833s | 376.175s | 32,089 / 30,951 MiB |
| `singularity_4step` | 45.322s | 207.400s | 27,703 / 27,975 MiB |

All outputs: 768 × 1344, 24 fps, video plus audio. Case 1: 107 frames / 4.459s. Case 2: 362 frames / 15.084s. Aligned durations follow the existing H3 frame policy. Sampler cache reuse is rejected by the test harness.

## Partial visual review

Frame sampling is not a full motion, identity, lip-sync, or audio review. Spoken words and soundscape remain unverified. All four case-1 outputs contain subtitles despite the explicit prohibition. Singularity retains the three-person composition in the 0s/2s/4s samples, but still fails that subtitle criterion. LightX2V eight-step also copies reference-caption text and generates garbled captions.

[Case 1 frame comparison](../../../runtime/ref2va-benchmarks/review/case1-comparison.jpg) · [Case 2 frame comparison](../../../runtime/ref2va-benchmarks/review/case2-comparison.jpg)

Case 2 observations are recorded in [visual-review notes](../../../runtime/ref2va-benchmarks/case2-visual-review.json). Do not treat successful media validation as full prompt compliance. Case 1 uses all inputs as references; the workflow does not provide hard first-frame conditioning.

## Outputs and evidence

| Variant / case | Video | Run metadata |
| --- | --- | --- |
| `baseline` / 1 | [MP4](../../../runtime/ref2va-benchmarks/baseline_case1_5948df3c/output.mp4) | [timing and media checks](../../../runtime/ref2va-benchmarks/baseline_case1_5948df3c/result.json) |
| `baseline` / 2 | [MP4](../../../runtime/ref2va-benchmarks/baseline_case2_aa2ae1cf/output.mp4) | [timing and media checks](../../../runtime/ref2va-benchmarks/baseline_case2_aa2ae1cf/result.json) |
| `lightx2v_8step` / 1 | [MP4](../../../runtime/ref2va-benchmarks/lightx2v_8step_case1_c587ea6c/output.mp4) | [timing and media checks](../../../runtime/ref2va-benchmarks/lightx2v_8step_case1_c587ea6c/result.json) |
| `lightx2v_8step` / 2 | [MP4](../../../runtime/ref2va-benchmarks/lightx2v_8step_case2_2ed8ad6d/output.mp4) | [timing and media checks](../../../runtime/ref2va-benchmarks/lightx2v_8step_case2_2ed8ad6d/result.json) |
| `pai_8step` / 1 | [MP4](../../../runtime/ref2va-benchmarks/pai_8step_case1_070406de/output.mp4) | [timing and media checks](../../../runtime/ref2va-benchmarks/pai_8step_case1_070406de/result.json) |
| `pai_8step` / 2 | [MP4](../../../runtime/ref2va-benchmarks/pai_8step_case2_abaec255/output.mp4) | [timing and media checks](../../../runtime/ref2va-benchmarks/pai_8step_case2_abaec255/result.json) |
| `singularity_4step` / 1 | [MP4](../../../runtime/ref2va-benchmarks/singularity_4step_case1_e8b001a6/output.mp4) | [timing and media checks](../../../runtime/ref2va-benchmarks/singularity_4step_case1_e8b001a6/result.json) |
| `singularity_4step` / 2 | [MP4](../../../runtime/ref2va-benchmarks/singularity_4step_case2_11def1b8/output.mp4) | [timing and media checks](../../../runtime/ref2va-benchmarks/singularity_4step_case2_11def1b8/result.json) |

Each run directory also contains the exact submitted graph, ComfyUI history, and sampled GPU utilization/memory. Local `runtime` evidence is ignored by Git; preserve it separately when sharing results.

## Verification and reproduction

- CPU tests: 47 passed, 10 skipped (8 opt-in live tests and 2 Firestore tests).
- Live tests: 8 passed across two selected-variant runs of `worker/tests/test_h3_email_cases.py`.
- All three frontend workflows were opened and API-exported in ComfyUI; native prompt validation passed for each.
- Three new model files were verified against the pinned SHA-256 hashes in [models.json](models.json).
- [Environment and input hashes](../../../runtime/ref2va-benchmarks/environment.json).
- [Native frontend validation](../../../runtime/ref2va-benchmarks/native-validation.json).
- [Restored services](../../../runtime/ref2va-benchmarks/restored-services.json): both ComfyUI instances and pull-workers active, queues empty; PDD node available on both instances.
- [Installation and repeat-run instructions](README.md).
- Raw prompts: [case 1](../../../tests/fixtures/h3_email_cases/case_1/prompt.txt), [case 2](../../../tests/fixtures/h3_email_cases/case_2/prompt.txt).

The LightX2V eight-step experiment retains the existing Ref2VA video/audio shifts 12/3 because the publisher has not documented a separate recipe for this file. PAI uses its full PDD adapter and trained eight-step sigma schedule. Production workflow registration is unchanged.

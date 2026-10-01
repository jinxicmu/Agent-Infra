# H3 email test cases

These two cases were retrieved from the emails **h3 testing case 1** and
**h3 testing case 2**, dated October 1, 2026. Each directory contains the original
three image attachments in displayed order, the extracted prompt, an API request
template, and source/parameter/image-checksum metadata in `case.json`.

| Case | Scenario | Request | Expected media contract |
| --- | --- | --- | --- |
| 1 | Shop confrontation with storyboard and two identity references | Ref2VA, 768P, 9:16, 4 seconds, native audio | 768 × 1344, 24 fps, 107 frames (about 4.46 seconds) |
| 2 | Hospital and medical-resource transformation with three visual references | Ref2VA, 768P, 9:16, 15 seconds, native audio | 768 × 1344, 24 fps, 362 frames (about 15.08 seconds) |

The frame counts follow the repository's H3 frame-alignment policy, so encoded
duration differs slightly from requested duration. Prompts are preserved as
displayed in the email, excluding its separate JSON parameter block. Email
`durationSeconds` maps to API `duration`; `generateAudio` is omitted from the
request because the API has no such field and the approved Ref2VA graph already
produces native audio. Fixture preparation does not submit generation jobs;
the opt-in benchmark below runs these cases locally.

## Workflow limitation

Case 1 asks for Picture 1 as an exact first frame and Pictures 2–3 as identity
references. The current API rejects mixing `first_frame` and `reference_image`.
This case therefore uses all three as ordered references and retains the exact
first-frame instruction in its prompt. It is a best-effort visual evaluation,
not proof that hard first-frame conditioning is supported. Changing the workflow
to provide that guarantee is outside this fixture change.

Case 2 uses all images as weak references. Its summary asks for one continuous
shot while its detailed prompt names three timed shots. Both instructions are
preserved for evaluation rather than silently rewritten.

## Local contract verification

From the repository root:

```bash
.venv/bin/python -m pytest worker/tests/test_h3_email_cases.py -q
```

The two cases run against the baseline and three experimental variants. They validate the API parameters, original image checksums and
dimensions, exact prompt transfer, reference ordering, canvas, duration, and
audio connection through the real worker graph builder. Image fetching uses the
local attachments. By default they do not evaluate generated video quality or use a GPU.
For opt-in live measurements through the same test file, see
[the Ref2VA experiment instructions](../../../workflows/experiments/ref2va/README.md).

## Prepare a generation request

Make each case's three images available at HTTPS URLs accessible to the worker
(using the project's approved input hosting). The templates intentionally have
unresolved URL placeholders. Supply URLs in Picture 1, 2, 3 order:

```bash
.venv/bin/python tests/prepare_h3_email_case.py 1 \
  --image-url "$PICTURE_1_URL" \
  --image-url "$PICTURE_2_URL" \
  --image-url "$PICTURE_3_URL" > /tmp/h3-case-1-request.json
```

Use `2` for case 2 with its own image URLs. The helper validates and emits JSON;
it does not upload images or submit jobs. Submit the prepared JSON using the
authenticated `POST /v2/video_generation` flow in `API_CLIENT_GUIDE.md`, then poll
`GET /v2/query/video_generation?task_id=...`. Record the task ID, workflow revision,
terminal status, output media metadata, and review results. Never submit a raw
template with unresolved placeholders.

## Generated-video acceptance checks

For both cases, confirm completion, the media contract above, playable video and
audio, correct image associations, and no unrequested voices. Record each item
as pass/fail with a timestamp or frame reference; automated contract success is
not a visual-quality pass.

**Case 1 — shop confrontation**

- Compare the opening frame to Picture 1: shop, broken display case, all three
  people, placement, pose, clothing, props, lighting, and camera composition.
  Report deviations explicitly given the Ref2VA limitation.
- Preserve Subject 1 from Picture 2 and Subject 2 from Picture 3 without identity
  swaps. Move forward from the opening as Derek points toward Carter and the
  woman reaches toward the phone in her pocket.
- Derek says “Cut her off. Right now.” once, with no other speech. Include the
  requested glass/shoe sounds and low strings.
- No subtitles, gameplay, or full-screen UI. The reference images contain text;
  it must not leak into dialogue or generated captions.

**Case 2 — medical-resource transformation**

- 0–5 seconds: cold-toned luxury hospital, red-haired woman beside the sick girl,
  slow forward camera push. The woman says “No limited medical resources. I will
  open every channel to save you.” with no added speech.
- 5–10 seconds: a controlled golden-coin stream transforms into equipment,
  supplies, and connected medical infrastructure while preserving ward continuity.
- 10–15 seconds: medical teams organize around the child and activate resources;
  the woman remains beside her.
- Final overlay reads `TOP TYCOON | MEDICAL INDUSTRY ACTIVATED | FULL RESOURCE SUPPORT`.
  Include hospital/equipment ambience; no added non-diegetic music. Do not copy
  reference-image captions or their implied dialogue.

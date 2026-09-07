# ComfyUI workflow library

Open [GPU 0](http://127.0.0.1:8188) or [GPU 1](http://127.0.0.1:8189), refresh the page, and choose **Workflows → Agent-Infra**:

- **I2V - Turbo 4step 768P** — first-frame image; no last-frame conditioning.
- **FL2V - Turbo 4step 768P** — first and last image inputs.
- **Ref2VA - Turbo 4step 544P** — reference images and native audio output; use `<Picture 1>`, `<Picture 2>`, etc. in the prompt. Add LoadImage nodes and connect the growing `ref_images` inputs for more references.

All entries contain editable prompts, images, duration and ResolutionSelector controls. The library uses ComfyUI's native megapixel/aspect controls: `480P = 0.3828125`, `544P = 0.5`, `720P = 0.861328125`, `768P = 0.98` megapixels, rounding to multiples of 32. Defaults match the deployed API workflow families. The installed demo image lets you run immediately; replace it with your own upload.

## Manual sessions on the shared GPUs

The same ComfyUI instances serve API workers. Before using GPU 0 manually:

```bash
systemctl --user stop pull-worker@0
```

This gracefully finishes the worker's current cloud task before stopping; wait for the command to return. ComfyUI stays running, and GPU 1 continues serving the API. Then open port 8188, select a workflow, edit inputs, and click **Run**. Once your manual queue finishes:

```bash
systemctl --user start pull-worker@0
```

For GPU 1 / port 8189, use `pull-worker@1`. Do not mix manual queued jobs with an active API worker: the worker owns its ComfyUI queue and may drain it during task completion/recovery.

Manual videos appear in SaveVideo and that instance's `output/video/manual/` directory. They do not become Cloud Run tasks or automatically upload to GCS.

## Publishing and future workflow additions

Every newly offered workflow must ship both its internal API graph and an editable frontend JSON here, be installed in each active ComfyUI user library, and pass a frontend load/export plus native prompt validation before release. The API-only JSON is not a replacement for a library entry.

Generate the current entries:

```bash
python -m workflows.publish_comfyui --build
```

Install to an instance's **actual** `--user-directory`:

```bash
python -m workflows.publish_comfyui \
  --user-dir /path/to/instance/user \
  --input-dir /path/to/instance/input \
  --example-image /path/to/demo.png
```

`--example-image` is optional; without it users must upload/select their image before running. The installer preserves differently edited library files by refusing to overwrite them; rename your customized version before installing an update. Demo images stay local and are not included in Git.

Workstation installation locations:

- `Agent-Infra/runtime/worker-0/state/user/default/workflows/Agent-Infra/`
- `Agent-Infra/runtime/worker-1/state/user/default/workflows/Agent-Infra/`
- `/home/kakarot/Documents/zarli_ai/ComfyUI/user/default/workflows/Agent-Infra/` (default library)

The first two are used by the running services. No service restart is needed for workflow-library files.

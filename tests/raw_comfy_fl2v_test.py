"""Phase 3 raw ComfyUI API test for the minimax_h3_fl2v_api workflow.

Loads the captured API-format workflow, patches in a short test prompt plus
first_frame and last_frame images already present in ComfyUI/input/, submits
it directly to ComfyUI's /prompt endpoint, polls /history until done, and
verifies the resulting MP4 with ffprobe. No FastAPI layer involved yet --
this only proves the captured workflow graph is valid and executable.
"""
import copy
import json
import subprocess
import sys
import time
import urllib.request

COMFY_BASE = "http://127.0.0.1:8188"
WORKFLOW_PATH = "/workspace/ai_studio_api_v2/workflows/minimax_h3_fl2v_api.json"
CLIENT_ID = "phase3-raw-test"


def comfy_get(path):
    with urllib.request.urlopen(f"{COMFY_BASE}{path}", timeout=10) as r:
        return json.load(r)


def comfy_post(path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"{COMFY_BASE}{path}", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def build_prompt():
    with open(WORKFLOW_PATH) as f:
        graph = json.load(f)
    graph = copy.deepcopy(graph)

    # First frame image (node 114 already loads "clipboard (1).png")
    graph["114"]["inputs"]["image"] = "clipboard (1).png"

    # Add a LoadImage node for last_frame and wire it into the MiniMaxH3ImageToVideo node
    graph["200"] = {
        "inputs": {"image": "clipboard.png"},
        "class_type": "LoadImage",
        "_meta": {"title": "Load Image (last_frame, test)"},
    }
    graph["105:104"]["inputs"]["last_frame"] = ["200", 0]

    # Short deterministic test prompt
    graph["105:104"]["inputs"]["prompt"] = (
        "integrated_multimodal_description: A brief test clip transitioning between two still frames.\n"
        "overall_soundscape: Silence.\n"
        "non_diegetic_music: N/A\n"
    )

    return graph


def main():
    prompt = build_prompt()
    resp = comfy_post("/prompt", {"prompt": prompt, "client_id": CLIENT_ID})
    if "error" in resp:
        print("SUBMIT FAILED:", json.dumps(resp, indent=2))
        sys.exit(1)
    prompt_id = resp["prompt_id"]
    print("submitted prompt_id:", prompt_id)

    deadline = time.time() + 600
    history = None
    while time.time() < deadline:
        hist_all = comfy_get(f"/history/{prompt_id}")
        if prompt_id in hist_all:
            history = hist_all[prompt_id]
            status = history.get("status", {})
            if status.get("completed"):
                break
            if status.get("status_str") == "error":
                print("EXECUTION FAILED:", json.dumps(status, indent=2))
                sys.exit(1)
        time.sleep(3)
    else:
        print("TIMED OUT waiting for completion")
        sys.exit(1)

    outputs = history.get("outputs", {})
    save_node_out = outputs.get("92", {})
    videos = save_node_out.get("videos") or save_node_out.get("gifs") or save_node_out.get("images") or []
    if not videos:
        print("NO VIDEO OUTPUT FOUND:", json.dumps(outputs, indent=2))
        sys.exit(1)

    video_info = videos[0]
    filename = video_info["filename"]
    subfolder = video_info.get("subfolder", "")
    video_type = video_info.get("type", "output")
    local_path = f"/workspace/runpod-slim/ComfyUI/{video_type}/{subfolder}/{filename}".replace("//", "/")
    print("output file:", local_path)

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,size", "-show_entries",
         "stream=codec_type,codec_name,width,height", "-of", "json", local_path],
        capture_output=True, text=True,
    )
    if probe.returncode != 0:
        print("FFPROBE FAILED:", probe.stderr)
        sys.exit(1)

    print("ffprobe result:")
    print(probe.stdout)
    print("PHASE 3 RAW TEST: PASS")


if __name__ == "__main__":
    main()

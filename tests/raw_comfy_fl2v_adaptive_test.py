"""Phase 3b: validate the ADAPTIVE resolution path (image-derived width/height),
since this is the only ratio mode the public API will expose for fl2v/i2v.

Wires: LoadImage -> ImageScaleToTotalPixels -> (scaled image feeds both
first_frame and GetImageSize) instead of the fixed ResolutionSelector path.
"""
import copy
import json
import subprocess
import sys
import time
import urllib.request

COMFY_BASE = "http://127.0.0.1:8188"
WORKFLOW_PATH = "/workspace/ai_studio_api_v2/workflows/minimax_h3_fl2v_api.json"
CLIENT_ID = "phase3b-adaptive-test"


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

    graph["114"]["inputs"]["image"] = "clipboard (1).png"

    # last_frame, also routed through the same scaler for a consistent size
    graph["200"] = {
        "inputs": {"image": "clipboard.png"},
        "class_type": "LoadImage",
        "_meta": {"title": "Load Image (last_frame, test)"},
    }
    graph["201"] = {
        "inputs": {"upscale_method": "nearest-exact", "megapixels": 0.98, "resolution_steps": 32, "image": ["200", 0]},
        "class_type": "ImageScaleToTotalPixels",
        "_meta": {"title": "Scale Image to Total Pixels (last_frame)"},
    }

    # adaptive path: scale first_frame, derive width/height from it
    graph["119"]["inputs"]["image"] = ["114", 0]
    graph["119"]["inputs"]["megapixels"] = 0.98
    # node 120 (GetImageSize) already reads node 119's output per the captured graph

    node = graph["105:104"]["inputs"]
    node["first_frame"] = ["119", 0]
    node["last_frame"] = ["201", 0]
    node["width"] = ["120", 0]
    node["height"] = ["120", 1]
    node["prompt"] = (
        "integrated_multimodal_description: A brief test clip transitioning between two still frames, adaptive resolution path.\n"
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
    print("PHASE 3b ADAPTIVE TEST: PASS")


if __name__ == "__main__":
    main()

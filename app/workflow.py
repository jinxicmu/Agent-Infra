import copy
import json
import secrets

from app import config
from app.image_fetcher import fetch_image
from app.schemas import CreateVideoRequest

_GRAPH_CACHE: dict[str, dict] = {}


def _load_graph(workflow_file: str) -> dict:
    if workflow_file not in _GRAPH_CACHE:
        with open(config.WORKFLOWS_DIR / workflow_file) as f:
            _GRAPH_CACHE[workflow_file] = json.load(f)
    return copy.deepcopy(_GRAPH_CACHE[workflow_file])


def build_prompt_graph(
    req: CreateVideoRequest,
    workflow_type: str,
    workflow_file: str,
    task_id: str,
    resolution_preset: dict,
) -> dict:
    """Patches the captured MiniMaxH3ImageToVideo API graph for this request.

    first_frame / last_frame (when present) are each routed through their own
    ImageScaleToTotalPixels node; width/height are always derived adaptively
    from whichever scaled image is present (first_frame preferred), matching
    the only ratio value ('adaptive') this workflow_type accepts.
    """
    graph = _load_graph(workflow_file)
    core = graph["105:104"]["inputs"]
    graph["92"]["inputs"]["filename_prefix"] = f"video/{task_id}"

    text_item = next(c for c in req.content if c.type == "text")
    core["prompt"] = (
        f"integrated_multimodal_description: {text_item.text}\n"
        "overall_soundscape: N/A\n"
        "non_diegetic_music: N/A\n"
    )

    graph["105:111"]["inputs"]["value"] = req.duration
    graph["105:15"]["inputs"]["noise_seed"] = secrets.randbelow(2**32)

    images_by_role = {}
    for item in req.content:
        if item.type != "image_url":
            continue
        role = item.role or "first_frame"
        images_by_role[role] = item.image_url

    next_id = max(int(k) for k in graph if k.isdigit()) + 1
    size_source_node = None

    for role, node_input_name in (("first_frame", "first_frame"), ("last_frame", "last_frame")):
        image_url = images_by_role.get(role)
        if not image_url:
            core.pop(node_input_name, None)
            continue

        filename = fetch_image(image_url, task_id, role)
        load_id = str(next_id)
        next_id += 1
        graph[load_id] = {
            "inputs": {"image": filename},
            "class_type": "LoadImage",
            "_meta": {"title": f"Load Image ({role})"},
        }

        scale_id = str(next_id)
        next_id += 1
        graph[scale_id] = {
            "inputs": {
                "upscale_method": "nearest-exact",
                "megapixels": resolution_preset["megapixels"],
                "resolution_steps": resolution_preset["resolution_steps"],
                "image": [load_id, 0],
            },
            "class_type": "ImageScaleToTotalPixels",
            "_meta": {"title": f"Scale Image to Total Pixels ({role})"},
        }

        core[node_input_name] = [scale_id, 0]
        if size_source_node is None:
            size_source_node = scale_id

    if size_source_node is None:
        raise ValueError("build_prompt_graph requires at least one image for the enabled workflow types")

    size_id = str(next_id)
    next_id += 1
    graph[size_id] = {
        "inputs": {"image": [size_source_node, 0]},
        "class_type": "GetImageSize",
        "_meta": {"title": "Get Image Size"},
    }
    core["width"] = [size_id, 0]
    core["height"] = [size_id, 1]

    return graph

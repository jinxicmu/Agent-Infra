import json

from app import config
from app.errors import ApiError
from app.schemas import CreateVideoRequest

with open(config.WORKFLOWS_DIR / "WORKFLOW_REGISTRY.json") as f:
    REGISTRY = json.load(f)

with open(config.WORKFLOWS_DIR / "PRESETS.json") as f:
    PRESETS = json.load(f)


def infer_workflow_type(req: CreateVideoRequest) -> str:
    texts = [c for c in req.content if c.type == "text"]
    images = [c for c in req.content if c.type == "image_url"]

    if len(texts) != 1 or not (texts[0].text or "").strip():
        raise ApiError(400, "INVALID_REQUEST", "content must include exactly one non-empty text item")

    for img in images:
        if img.role not in (None, "first_frame", "last_frame"):
            raise ApiError(400, "UNSUPPORTED_CONTENT_ROLE", f"Unsupported image role: {img.role}")
        if not img.image_url:
            raise ApiError(400, "INVALID_REQUEST", "image_url content item missing image_url")

    roles = [img.role for img in images]
    has_first = "first_frame" in roles or (len(images) == 1 and roles[0] is None)
    has_last = "last_frame" in roles

    if len(images) == 0:
        return "t2v"
    if len(images) == 1 and has_first and not has_last:
        return "i2v_first"
    if len(images) == 1 and has_last and not has_first:
        return "i2v_last"
    if len(images) == 2 and has_first and has_last:
        return "fl2v"

    raise ApiError(400, "UNSUPPORTED_WORKFLOW_COMBINATION", "Unsupported combination of image roles in content")


def resolve_workflow(model: str, workflow_type: str) -> dict:
    model_registry = REGISTRY.get(model)
    if model_registry is None:
        raise ApiError(400, "UNSUPPORTED_MODEL", f"Unsupported model: {model}")

    entry = model_registry.get(workflow_type)
    if entry is None or not entry.get("enabled"):
        raise ApiError(
            400,
            "UNSUPPORTED_WORKFLOW_COMBINATION",
            f"workflow_type '{workflow_type}' is not enabled for model '{model}'",
        )
    return entry


def validate_resolution(model: str, resolution: str):
    presets = PRESETS.get(model, {})
    if resolution not in presets.get("resolutions", {}):
        raise ApiError(400, "UNSUPPORTED_RESOLUTION", f"Unsupported resolution: {resolution}")
    return presets["resolutions"][resolution]


def validate_duration(model: str, duration: int):
    presets = PRESETS.get(model, {})
    if str(duration) not in presets.get("durations", {}):
        raise ApiError(400, "UNSUPPORTED_DURATION", f"Unsupported duration: {duration}")


def validate_ratio(model: str, workflow_type: str, ratio: str):
    presets = PRESETS.get(model, {})
    policy = presets.get("ratio_policy", {}).get(workflow_type, {})
    allowed = policy.get("allowed", [])
    if ratio not in allowed:
        raise ApiError(
            400,
            "INVALID_RATIO_FOR_WORKFLOW",
            f"ratio '{ratio}' not allowed for workflow_type '{workflow_type}'; allowed: {allowed}",
        )

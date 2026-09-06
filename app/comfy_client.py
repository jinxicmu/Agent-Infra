import requests

from app import config


def submit_prompt(graph: dict, client_id: str) -> str:
    resp = requests.post(
        f"{config.COMFY_BASE_URL}/prompt",
        json={"prompt": graph, "client_id": client_id},
        timeout=30,
    )
    data = resp.json()
    if resp.status_code != 200 or "prompt_id" not in data:
        raise RuntimeError(f"ComfyUI /prompt submission failed: {data}")
    return data["prompt_id"]


def get_history(prompt_id: str) -> dict | None:
    resp = requests.get(f"{config.COMFY_BASE_URL}/history/{prompt_id}", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data.get(prompt_id)


def get_queue_depth() -> int:
    """Number of tasks currently running or pending inside ComfyUI (running + queued)."""
    resp = requests.get(f"{config.COMFY_BASE_URL}/queue", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return len(data.get("queue_running", [])) + len(data.get("queue_pending", []))


def is_healthy() -> bool:
    try:
        resp = requests.get(f"{config.COMFY_BASE_URL}/system_stats", timeout=5)
        return resp.status_code == 200
    except requests.RequestException:
        return False

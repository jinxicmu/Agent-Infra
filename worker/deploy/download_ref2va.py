"""Install pinned Ref2VA weights, verifying their HF SHA-256 before publication.

Usage: python -m worker.deploy.download_ref2va /path/to/ComfyUI/models
Existing files are checked, never silently overwritten. Keep model files out of Git.
"""
import hashlib
import json
from pathlib import Path
import sys
import requests


def digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024**2), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def install(model_root):
    provenance = Path(__file__).resolve().parents[2] / 'workflows/REF2VA_PROVENANCE.json'
    for model in json.loads(provenance.read_text())['models']:
        target = model_root / model['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        candidate = target if target.exists() else target.with_suffix('.download')
        if candidate != target:
            with requests.get(model['url'], stream=True, timeout=(20, 60)) as response:
                response.raise_for_status()
                with candidate.open('wb') as output:
                    for chunk in response.iter_content(4 * 1024**2):
                        output.write(chunk)
        if candidate.stat().st_size != model['size'] or digest(candidate) != model['sha256']:
            raise RuntimeError(f'Invalid model size/checksum: {model["path"]}')
        if candidate != target:
            candidate.replace(target)
        print(f'Verified {model["path"]}', flush=True)


if __name__ == '__main__':
    install(Path(sys.argv[1]).expanduser().resolve())

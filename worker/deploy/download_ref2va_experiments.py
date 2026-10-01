"""Download only the three pinned experimental weights; verify before publishing."""
import argparse
import json
from pathlib import Path

import requests

from worker.deploy.download_ref2va import digest


def install(root):
    manifest = Path(__file__).resolve().parents[2] / 'workflows/experiments/ref2va/models.json'
    for model in json.loads(manifest.read_text())['models']:
        target = root / model['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        candidate = target if target.exists() else target.with_suffix('.download')
        if candidate != target:
            print(f'Downloading {model["id"]}', flush=True)
            with requests.get(model['url'], stream=True, timeout=(20, 60)) as response:
                response.raise_for_status()
                with candidate.open('wb') as output:
                    for chunk in response.iter_content(8 * 1024**2):
                        output.write(chunk)
        if candidate.stat().st_size != model['size'] or digest(candidate) != model['sha256']:
            raise RuntimeError(f'Invalid size or checksum: {model["path"]}')
        if candidate != target:
            candidate.replace(target)
        print(f'Verified {model["id"]}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model_root', type=Path)
    install(parser.parse_args().model_root.expanduser().resolve())

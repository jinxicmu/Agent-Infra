"""Email-derived contract cases; local images, no network or GPU required."""
import hashlib
import json
import os
import subprocess
from pathlib import Path
import shutil
from types import SimpleNamespace

from PIL import Image
import pytest

from cloudrun.schemas import CreateVideoRequest
from cloudrun.validation import validate
from worker.workflow import build_prompt_graph
from workflows.parameters import frame_count
from workflows.ref2va_experiments import VARIANTS, apply_variant


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('variant', list(VARIANTS))
@pytest.mark.parametrize('case_number,duration,frames', [(1, 4, 107), (2, 15, 362)],
                         ids=['shop-confrontation', 'medical-resource-transformation'])
def test_email_case_preserves_prompt_images_and_audio(
        case_number, duration, frames, variant, tmp_path, monkeypatch):
    case = ROOT / 'tests' / 'fixtures' / 'h3_email_cases' / f'case_{case_number}'
    metadata = json.loads((case / 'case.json').read_text())
    body = json.loads((case / 'request.template.json').read_text())
    prompt = (case / 'prompt.txt').read_text().rstrip('\n')
    assert body['content'][0]['text'] == prompt
    assert metadata['original_parameters']['generateAudio'] is True
    assert metadata['original_parameters']['durationSeconds'] == duration
    inputs = {}
    for item, asset in zip(body['content'][1:], metadata['images'], strict=True):
        path = case / asset['file']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == asset['sha256']
        with Image.open(path) as image:
            assert list(image.size) == asset['dimensions']
            image.verify()
        item['image_url'] = f'https://example.invalid/{asset["file"]}'
        inputs[item['image_url']] = path
    request = validate(CreateVideoRequest(**body))
    assert (request['workflow_type'], request['resolution'], request['ratio'],
            request['duration']) == ('ref2va', '768P', '9:16', duration)
    fetched = []

    def fetch(url, task_id, role, directory, check):
        fetched.append(url)
        name = f'{task_id}_{role}.png'
        shutil.copyfile(inputs[url], directory / name)
        return name

    monkeypatch.setattr('worker.workflow.fetch_image', fetch)
    workflow_dir = ROOT / 'workflows'
    settings = SimpleNamespace(workflow_dir=workflow_dir, input_dir=tmp_path,
                               manifest=json.loads((workflow_dir / 'CAPABILITIES.json').read_text()))
    graph = build_prompt_graph({'task_id': f'gen_email_{case_number}', 'seed': 42,
                                'workflow_type': 'ref2va', 'request': request}, settings)
    graph = apply_variant(graph, variant)
    core = graph['136']['inputs']
    assert core['prompt'] == prompt
    assert (core['width'], core['height']) == (768, 1344)
    assert graph['132']['inputs']['value'] == duration
    assert frame_count(duration) == frames
    assert fetched == list(inputs)
    for i in range(3):
        assert core[f'ref_images.ref_image_{i}'] == [f'ref_image_{i}', 0]
        assert graph[f'ref_image_{i}']['inputs']['image'] == f'gen_email_{case_number}_reference_image_{i}.png'
    assert 'ref_images.ref_image_3' not in core
    assert graph['130']['inputs']['audio'] == ['121', 0]

    if variant == 'pai_8step':
        assert graph['148']['inputs']['nfe'] == '8'
        assert graph['148']['inputs']['lora_strength'] == 1.0
        assert graph['148']['inputs']['head_strength'] == 1.0
        assert graph['125']['inputs']['sigmas'] == ['148', 1]
        assert graph['126']['inputs']['model'] == ['148', 0]
        assert '145' not in graph and '124' not in graph
    else:
        assert graph['124']['inputs']['steps'] == VARIANTS[variant]['steps']
    if 'lora' in VARIANTS[variant]:
        assert graph['145']['inputs']['lora_name'] == VARIANTS[variant]['lora']
    if variant == 'singularity_4step':
        assert graph['127']['inputs']['unet_name'] == VARIANTS[variant]['model']
        assert '4step_v0.1' in graph['145']['inputs']['lora_name']


@pytest.mark.skipif(not os.getenv('H3_BENCHMARK_URL'), reason='Opt-in GPU benchmark')
@pytest.mark.parametrize('variant', list(VARIANTS))
@pytest.mark.parametrize('case_number', [1, 2])
def test_email_case_live_performance(case_number, variant, monkeypatch):
    from worker.ref2va_benchmark import measure
    selected = os.getenv('H3_BENCHMARK_VARIANTS', ','.join(VARIANTS)).split(',')
    if variant not in selected:
        pytest.skip('Variant not selected for this run')
    gpu = int(os.getenv('H3_BENCHMARK_GPU', '0'))
    state = subprocess.run(['systemctl', '--user', 'show', f'pull-worker@{gpu}',
                            '--property=ActiveState', '--value'],
                           capture_output=True, text=True, check=True)
    assert state.stdout.strip() == 'inactive', 'Stop the pull-worker and wait for its task to finish'
    input_dir = Path(os.environ['H3_BENCHMARK_INPUT_DIR']).resolve()
    case = ROOT / 'tests/fixtures/h3_email_cases' / f'case_{case_number}'
    request = json.loads((case / 'request.template.json').read_text())
    images = {}
    for i, item in enumerate(request['content'][1:], 1):
        url = f'https://example.invalid/case_{case_number}/picture_{i}.png'
        item['image_url'] = url
        images[url] = case / f'picture_{i}.png'
    request = validate(CreateVideoRequest(**request))

    def local_image(url, task_id, role, directory, check):
        relative = Path('h3_email_cases') / f'case_{case_number}' / images[url].name
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            assert target.read_bytes() == images[url].read_bytes(), 'Existing benchmark image differs'
        else:
            shutil.copyfile(images[url], target)
        return relative.as_posix()

    monkeypatch.setattr('worker.workflow.fetch_image', local_image)
    settings = SimpleNamespace(workflow_dir=ROOT/'workflows', input_dir=input_dir,
        manifest=json.loads((ROOT/'workflows/CAPABILITIES.json').read_text()))
    graph = build_prompt_graph({'task_id': f'gen_benchmark_{case_number}', 'seed': 42,
                                'workflow_type': 'ref2va', 'request': request}, settings)
    result = measure(apply_variant(graph, variant), request, variant, case_number,
                     os.environ['H3_BENCHMARK_URL'],
                     os.environ.get('H3_BENCHMARK_OUTPUT_DIR', 'runtime/ref2va-benchmarks'),
                     gpu=gpu)
    assert result['status'] == 'passed'

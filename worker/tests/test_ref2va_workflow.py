import json
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
from worker.workflow import build_prompt_graph
from workflows.export_ref2va import export_graph


def test_reference_source_export_and_turbo_overrides():
    root = Path(__file__).resolve().parents[2] / 'workflows'
    graph = json.loads((root / 'minimax_h3_ref2va_api.json').read_text())
    assert graph == export_graph()
    assert graph['127']['inputs']['unet_name'] == 'minimax_h3_ref2va_pruned_int8_convrot.safetensors'
    assert graph['145']['inputs']['lora_name'] == 'minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors'
    assert graph['147']['inputs'] == {'model': ['145', 0], 'shift_video': 12, 'shift_audio': 3}
    assert graph['124']['inputs'] == {'model': ['147', 0], 'scheduler': 'simple', 'steps': 4, 'denoise': 1}
    assert graph['126']['inputs']['model'] == ['147', 0]
    assert graph['123']['inputs']['sampler_name'] == 'euler'
    assert graph['130']['inputs']['audio'] == ['121', 0]
    assert graph['136']['inputs']['ref_image_size'] == 'match'
    assert not {'137', '138', '139', '141', '142', '143', '144', '146'} & graph.keys()


def test_reference_order_adaptive_and_no_cross_task_conditioning(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2] / 'workflows'
    settings = SimpleNamespace(workflow_dir=root, input_dir=tmp_path,
                               manifest=json.loads((root / 'CAPABILITIES.json').read_text()))
    def fetch(url, task, role, directory, check):
        name = f'{task}_{role}.png'
        Image.new('RGB', (544, 960) if url.endswith('/0') else (960, 544)).save(directory / name)
        return name
    monkeypatch.setattr('worker.workflow.fetch_image', fetch)
    task = {'task_id': 'gen_a', 'seed': 99, 'workflow_type': 'ref2va', 'request': {
        'resolution': '544P', 'ratio': 'adaptive', 'duration': 4, 'content': [
            {'type': 'text', 'text': '<Picture 2> 看向 <Picture 1>。\n台词：你好。'},
            *[{'type': 'image_url', 'role': 'reference_image', 'image_url': f'https://example.com/{i}'}
              for i in range(9)]]}}
    graph = build_prompt_graph(task, settings)
    core = graph['136']['inputs']
    assert (core['width'], core['height']) == (544, 960)
    assert core['prompt'] == task['request']['content'][0]['text']
    assert graph['129']['inputs']['noise_seed'] == 99
    assert graph['132']['inputs']['value'] == 4
    for i in range(9):
        assert core[f'ref_images.ref_image_{i}'] == [f'ref_image_{i}', 0]
        assert graph[f'ref_image_{i}']['inputs']['image'] == f'gen_a_reference_image_{i}.png'
    task['request']['content'] = task['request']['content'][:2]
    task['task_id'] = 'gen_b'
    second = build_prompt_graph(task, settings)
    assert 'ref_images.ref_image_1' not in second['136']['inputs']
    assert second['ref_image_0']['inputs']['image'] == 'gen_b_reference_image_0.png'
    assert 'ref_images.ref_image_8' in core

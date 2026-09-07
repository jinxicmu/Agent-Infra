import json
import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from worker.workflow import build_prompt_graph
from worker.image_fetcher import fetch_image, InputError


def test_fixed_seed_and_independent_inputs(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]/'workflows'
    manifest = json.loads((root/'CAPABILITIES.json').read_text())
    fetch = Mock(side_effect=lambda url, task, role, directory, check: f'{task}_{role}.png')
    monkeypatch.setattr('worker.workflow.fetch_image', fetch)
    settings = SimpleNamespace(manifest=manifest, workflow_dir=root, input_dir=tmp_path)
    task = {'task_id':'gen_a', 'seed':112233, 'request':{'duration':5,'resolution':'768P','ratio':'16:9',
        'content':[{'type':'text','text':'move'},
                   {'type':'image_url','role':'first_frame','image_url':'https://example.com/a'},
                   {'type':'image_url','role':'last_frame','image_url':'https://example.com/b'}]}}
    graph = build_prompt_graph(task, settings)
    assert graph['105:15']['inputs']['noise_seed'] == 112233
    assert graph['92']['inputs']['filename_prefix'] == 'video/gen_a'
    assert graph['105:104']['inputs']['first_frame'] != graph['105:104']['inputs']['last_frame']
    assert fetch.call_args_list[0].args[3] == tmp_path
    assert build_prompt_graph(task, settings) == graph


def test_private_dns_and_credentials_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('127.0.0.1', 443))])
    for url in ('https://public.example/a.png', 'http://user:pass@example.com/a.png'):
        with pytest.raises(InputError):
            fetch_image(url, 'gen_a', 'first', tmp_path)


def test_export_matches_reviewed_source_and_prunes_editor_only_nodes():
    from workflows.export_h3 import export_graph
    root = Path(__file__).resolve().parents[2] / 'workflows'
    graph = json.loads((root / 'minimax_h3_fl2v_api.json').read_text())
    assert graph == export_graph()
    assert '119' not in graph and '120' not in graph
    assert graph['105:104']['inputs']['width'] == ['115', 0]
    assert graph['105:104']['inputs']['height'] == ['115', 1]
    assert graph['115']['inputs'] == {
        'aspect_ratio': '16:9 (Widescreen)', 'megapixels': 0.98, 'multiple': 32}
    assert graph['105:9']['inputs'] == {
        'scheduler': 'simple', 'steps': 4, 'denoise': 1, 'model': ['105:140', 0]}
    assert graph['105:140']['inputs'] == {
        'shift_video': 6, 'shift_audio': 3, 'model': ['105:130', 0]}
    assert graph['105:130']['inputs']['strength_model'] == 1
    assert graph['105:16']['inputs']['model'] == ['105:140', 0]
    assert graph['105:10']['inputs']['samples'] == ['105:14', 0]
    assert graph['105:23']['inputs']['samples'] == ['105:14', 0]
    assert graph['105:91']['inputs']['audio'] == ['105:23', 0]
    assert graph['105:91']['inputs']['color_space'] == 'sRGB'
    assert graph['105:111']['inputs']['value'] == 5  # exposed value overrides inner 2s


def test_runtime_only_binds_request_inputs_preserving_audio_and_source(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2] / 'workflows'
    manifest = json.loads((root / 'CAPABILITIES.json').read_text())
    settings = SimpleNamespace(manifest=manifest, workflow_dir=root, input_dir=tmp_path)
    monkeypatch.setattr('worker.workflow.fetch_image',
                        lambda url, task, role, directory, check: f'{task}_{role}.png')
    text = '镜头切入。\n台词：你这些症状从什么时候开始的？\n音效：语音清晰\nMusic: quiet piano.\n'
    task = {'task_id': 'gen_first', 'seed': 123, 'request': {
        'duration': 5, 'resolution':'768P', 'ratio': '16:9', 'content': [
            {'type': 'text', 'text': text},
            {'type': 'image_url', 'role': 'last_frame', 'image_url': 'https://example.com/b'},
            {'type': 'image_url', 'role': 'first_frame', 'image_url': 'https://example.com/a'}]}}
    graph = build_prompt_graph(task, settings)
    assert graph['105:104']['inputs']['prompt'] == text
    assert graph['105:104']['inputs']['first_frame'] == ['114', 0]
    assert graph['105:104']['inputs']['last_frame'] == ['121', 0]
    assert {v['class_type'] for v in graph.values()}.isdisjoint(
        {'ImageScaleToTotalPixels', 'GetImageSize'})
    source = json.loads((root / manifest['workflow_file']).read_text())
    changed = {k for k in graph if graph[k] != source.get(k)}
    assert changed == {'105:104', '105:15', '92', '114', '121'}
    task['task_id'], task['seed'] = 'gen_second', 456
    second = build_prompt_graph(task, settings)
    assert second['114']['inputs']['image'] == 'gen_second_first_frame.png'
    assert graph['114']['inputs']['image'] == 'gen_first_first_frame.png'
    assert graph['105:15']['inputs']['noise_seed'] == 123
    assert second['105:15']['inputs']['noise_seed'] == 456
    task['request']['ratio'] = '5:1'
    with pytest.raises(ValueError, match='INVALID_RATIO_FOR_WORKFLOW'):
        build_prompt_graph(task, settings)


def test_source_and_parameter_bindings_are_revision_fenced():
    import hashlib
    root = Path(__file__).resolve().parents[2] / 'workflows'
    manifest = json.loads((root / 'CAPABILITIES.json').read_text())
    assert manifest['parameter_map'] in manifest['files']
    assert manifest['source_workflow'] in manifest['files']
    for name, digest in manifest['files'].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    assert hashlib.sha256(json.dumps(manifest['files'], sort_keys=True).encode()).hexdigest() == manifest['revision']


def test_optional_last_frame_never_reuses_previous_task_conditioning(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2] / 'workflows'
    manifest = json.loads((root / 'CAPABILITIES.json').read_text())
    settings = SimpleNamespace(manifest=manifest, workflow_dir=root, input_dir=tmp_path)
    fetch = Mock(side_effect=lambda url, task, role, directory, check: f'{task}_{role}.png')
    monkeypatch.setattr('worker.workflow.fetch_image', fetch)
    task = {'task_id': 'gen_both', 'seed': 123, 'request': {
        'duration': 5, 'resolution':'768P', 'ratio': '16:9', 'content': [
            {'type': 'text', 'text': '自然对白'},
            {'type': 'image_url', 'role': 'first_frame', 'image_url': 'https://example.com/a'},
            {'type': 'image_url', 'role': 'last_frame', 'image_url': 'https://example.com/b'}]}}
    both = build_prompt_graph(task, settings)
    fetch.reset_mock()
    task['request']['content'].pop()
    task['task_id'] = 'gen_first_only'
    single = build_prompt_graph(task, settings)
    assert 'last_frame' not in single['105:104']['inputs']
    assert '121' not in single
    assert single['105:104']['inputs']['first_frame'] == ['114', 0]
    assert single['114']['inputs']['image'] == 'gen_first_only_first_frame.png'
    assert both['105:104']['inputs']['last_frame'] == ['121', 0]
    fetch.assert_called_once()
    assert fetch.call_args.args[2] == 'first_frame'
    task['request']['content'][-1]['role'] = 'last_frame'
    with pytest.raises(ValueError, match='one first_frame'):
        build_prompt_graph(task, settings)


@pytest.mark.parametrize('resolution,ratio,duration,dimensions', [
    ('480P','9:16',4,(480,832)), ('720P','1:1',1,(960,960)),
    ('768P','adaptive',6,(768,1344))])
def test_request_controls_canvas_and_duration(tmp_path,monkeypatch,resolution,ratio,duration,dimensions):
    from PIL import Image
    root=Path(__file__).resolve().parents[2]/'workflows'
    manifest=json.loads((root/'CAPABILITIES.json').read_text())
    settings=SimpleNamespace(manifest=manifest,workflow_dir=root,input_dir=tmp_path)
    Image.new('RGB',(768,1376)).save(tmp_path/'first.png')
    monkeypatch.setattr('worker.workflow.fetch_image',lambda *a:'first.png')
    task={'task_id':'gen_parameters','seed':42,'request':{'duration':duration,'ratio':ratio,'resolution':resolution,'content':[
        {'type':'text','text':'move naturally'},
        {'type':'image_url','role':'first_frame','image_url':'https://example.com/image'}]}}
    graph=build_prompt_graph(task,settings)
    assert (graph['105:104']['inputs']['width'],graph['105:104']['inputs']['height'])==dimensions
    assert graph['105:111']['inputs']['value']==duration
    assert '115' not in graph
    assert 'last_frame' not in graph['105:104']['inputs']

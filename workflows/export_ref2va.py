"""Reviewed Comfy-Org reference graph with ModelTC Ref2VA v0.1 Turbo sampling.

This is an offline, source-fenced exporter, not a general UI graph converter.
The base template's optional 20-step branch is removed explicitly.
"""
import hashlib
import json
from pathlib import Path
from workflows.export_h3 import WIDGETS

ROOT = Path(__file__).resolve().parent
SOURCE = 'source/video_minimax_h3_r2v.json'
SHA256 = '14b30659a057547e02bdd4bbbdda3f8670aa6d7d81d1d8d99c4f9ad1e2eabc44'


def export_graph():
    raw = (ROOT / SOURCE).read_bytes()
    if hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError('Reference source changed: review before exporting')
    source = json.loads(raw)
    links = {link[0]: link for link in source['links']}
    widgets = dict(WIDGETS, MiniMaxH3ReferenceToVideo=(
        'prompt', 'width', 'height', 'length', 'ref_image_size'),
        PrimitiveStringMultiline=('value',))
    graph = {}
    for node in source['nodes']:
        if node['type'] in {'MarkdownNote', 'ComfySwitchNode', 'PrimitiveInt', 'PrimitiveBoolean'}:
            continue
        # Older templates omit CreateVideo.color_space; keep its native default.
        names = widgets[node['type']]
        values = node.get('widgets_values') or []
        if node['type'] in {'CreateVideo', 'SaveVideo'}:
            names = names[:len(values)]
        inputs = {name: value for name, value in zip(names, values, strict=True) if name}
        for port in node.get('inputs', []):
            if port.get('link') is not None:
                _, origin, slot, *_ = links[port['link']]
                inputs[port['name']] = [str(origin), slot]
        graph[str(node['id'])] = {'class_type': node['type'], 'inputs': inputs}
    # Follow ModelTC's explicit Euler/simple/4-step, video12/audio3 setup.
    graph['123']['inputs']['sampler_name'] = 'euler'
    graph['124']['inputs'].update(model=['147', 0], scheduler='simple', steps=4, denoise=1)
    graph['126']['inputs']['model'] = ['147', 0]
    graph['147'] = {'class_type': 'MiniMaxH3SigmaShift', 'inputs': {
        'model': ['145', 0], 'shift_video': 12, 'shift_audio': 3}}
    graph['145']['inputs']['strength_model'] = 1
    graph['115']['inputs']['megapixels'] = .5
    graph['129']['inputs']['noise_seed'] = 42
    graph['136']['inputs']['ref_image_size'] = 'match'
    # Client supplies references and prompt; never execute bundled demo content.
    for name in list(graph['136']['inputs']):
        if name.startswith('ref_') and name != 'ref_image_size':
            del graph['136']['inputs'][name]
    graph['136']['inputs']['prompt'] = ''
    reachable = set()

    def visit(node_id):
        if node_id in reachable:
            return
        reachable.add(node_id)
        for value in graph[node_id]['inputs'].values():
            if isinstance(value, list):
                visit(value[0])

    visit('92')
    return {key: value for key, value in graph.items() if key in reachable}


if __name__ == '__main__':
    (ROOT / 'minimax_h3_ref2va_api.json').write_text(json.dumps(export_graph(), indent=2) + '\n')

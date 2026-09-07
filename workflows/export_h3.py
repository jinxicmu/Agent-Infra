"""Offline exporter for the reviewed Sage 41s UI workflow, not a general converter."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = 'source/MiniMax H3 - Turbo 4step 768p - Sage 41s.json'
SOURCE_SHA256 = 'a8fb242c8efb1fdb8ff3485df46dc77d2a9231cfe1e67443933dd59c743219e1'
# None denotes an editor-only widget, never an execution input.
WIDGETS = {
    'VAELoader': ('vae_name',),
    'UNETLoader': ('unet_name', 'weight_dtype'),
    'CLIPLoader': ('clip_name', 'type', 'device'),
    'RandomNoise': ('noise_seed', None),
    'KSamplerSelect': ('sampler_name',),
    'BasicScheduler': ('scheduler', 'steps', 'denoise'),
    'LoraLoaderModelOnly': ('lora_name', 'strength_model'),
    'MiniMaxH3SigmaShift': ('shift_video', 'shift_audio'),
    'MiniMaxH3ImageToVideo': ('prompt', 'width', 'height', 'length'),
    'ComfyMathExpression': ('expression',),
    'PrimitiveFloat': ('value',),
    'CreateVideo': ('fps', 'bit_depth', 'color_space'),
    'SaveVideo': ('filename_prefix', 'format', 'codec', None),
    'LoadImage': ('image', None),
    'ResolutionSelector': ('aspect_ratio', 'megapixels', 'multiple'),
    'ImageScaleToTotalPixels': ('upscale_method', 'megapixels', 'resolution_steps'),
    'GetImageSize': (), 'VAEDecode': (), 'VAEDecodeAudio': (),
    'BasicGuider': (), 'SamplerCustomAdvanced': (),
}


def export_graph(source_path=ROOT / SOURCE):
    raw = source_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError('Source changed: review the UI workflow before exporting')
    source = json.loads(raw)
    sub, = source['definitions']['subgraphs']
    outer = next(n for n in source['nodes'] if n['type'] == sub['id'])
    prefix = f"{outer['id']}:"
    top_links = {v[0]: v for v in source['links']}
    sub_links = {v['id']: v for v in sub['links']}
    names = [i['name'] for i in sub['inputs'] if i['type'] != 'IMAGE']
    exposed = dict(zip(names, outer['widgets_values'], strict=True))
    outer_inputs = {i['name']: i for i in outer['inputs']}
    output_link = sub_links[sub['outputs'][0]['linkIds'][0]]

    def top_value(link_id):
        _, origin, slot, *_ = top_links[link_id]
        if origin == outer['id']:
            if slot != 0:
                raise ValueError('Unexpected subgraph output')
            return [prefix + str(output_link['origin_id']), output_link['origin_slot']]
        return [str(origin), slot]

    def exposed_value(slot):
        name = sub['inputs'][slot]['name']
        link = outer_inputs.get(name, {}).get('link')
        if link is not None:
            return top_value(link)
        return exposed.get(name)

    graph = {}
    for scope, nodes in (('', source['nodes']), (prefix, sub['nodes'])):
        for node in nodes:
            kind = node['type']
            if kind in ('MarkdownNote', sub['id']):
                continue
            if node.get('mode', 0) != 0:
                raise ValueError('Bypassed/muted nodes need explicit review')
            inputs = {name: value for name, value in
                      zip(WIDGETS[kind], node.get('widgets_values') or [], strict=True)
                      if name is not None}
            for port in node.get('inputs', []):
                link_id = port.get('link')
                if link_id is None:
                    continue
                if not scope:
                    value = top_value(link_id)
                else:
                    link = sub_links[link_id]
                    if link['origin_id'] == sub['inputNode']['id']:
                        value = exposed_value(link['origin_slot'])
                    else:
                        value = [prefix + str(link['origin_id']), link['origin_slot']]
                if value is not None:
                    inputs[port['name']] = value
                else:
                    inputs.pop(port['name'], None)
            graph[scope + str(node['id'])] = {
                'inputs': inputs, 'class_type': kind,
                '_meta': {'title': node.get('title', kind)},
            }
    reachable = set()

    def visit(node_id):
        if node_id in reachable:
            return
        reachable.add(node_id)
        for value in graph[node_id]['inputs'].values():
            if isinstance(value, list) and len(value) == 2:
                visit(value[0])

    visit('92')
    return {key: value for key, value in graph.items() if key in reachable}


if __name__ == '__main__':
    (ROOT / 'minimax_h3_fl2v_api.json').write_text(
        json.dumps(export_graph(), ensure_ascii=False, indent=2) + '\n')

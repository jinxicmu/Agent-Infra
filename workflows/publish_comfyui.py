"""Build and install editable ComfyUI library entries for the supported workflows."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import uuid

ROOT = Path(__file__).resolve().parent
DEMO = 'Agent-Infra-demo.png'
PROMPT = '女医生抬头看向男患者，进入问诊状态。稳定构图。女医生说：你这些症状从什么时候开始的？环境安静，语音清晰。'
HELP = '''## Agent-Infra — editable local workflow
Upload your image(s), edit the prompt and duration, then click Run.
ResolutionSelector: choose aspect ratio and megapixels: 480P=0.3828125, 544P=0.5, 720P=0.861328125, 768P=0.98. Canvas rounds to multiples of 32.
Output: 24 fps video with native audio. Duration rounds up to the H3 frame grid.
For manual sessions, first stop this GPU's pull-worker service (see workflows/comfyui/README.md); wait for its current cloud task to finish. Restart the worker after manual jobs finish.
This runs directly on this ComfyUI GPU; outputs appear in SaveVideo and local output/video/manual. Cloud API task history and GCS upload apply to API submissions only.
'''


def read(name):
    return json.loads((ROOT / name).read_text())


def widgets(node, values, named):
    node['widgets_values'] = values
    node['widgets_values_named'] = named


def rebuild_links(document, links):
    nodes = {n['id']: n for n in document['nodes']}
    for node in nodes.values():
        for port in node.get('inputs', []):
            port['link'] = None
        for port in node.get('outputs', []):
            port['links'] = None
    for link_id, origin, slot, target, target_slot, kind in links:
        output = nodes[origin]['outputs'][slot]
        output['links'] = (output['links'] or []) + [link_id]
        nodes[target]['inputs'][target_slot]['link'] = link_id
    document['links'] = links
    document['last_link_id'] = max((v[0] for v in links), default=0)
    document['last_node_id'] = max(nodes)
    document['id'] = str(uuid.uuid5(uuid.NAMESPACE_URL, 'agent-infra/' + document['extra']['agent_infra_workflow']))
    document['revision'] = 0
    left = min(n['pos'][0] for n in nodes.values())
    top = min(n['pos'][1] for n in nodes.values())
    right = max(n['pos'][0] + n['size'][0] for n in nodes.values())
    bottom = max(n['pos'][1] + n['size'][1] for n in nodes.values())
    scale = min(1, 1300 / (right - left), 760 / (bottom - top))
    document['extra']['ds'] = {'scale': scale, 'offset': [-left + 40 / scale, -top + 40 / scale]}


def frame_workflow(last):
    doc = read('source/MiniMax H3 - Turbo 4step 768p - Sage 41s.json')
    kind = 'FL2V' if last else 'I2V'
    doc['extra'] = {'agent_infra_workflow': kind}
    doc['nodes'] = [n for n in doc['nodes'] if n['id'] not in {117, 118, 119, 120}]
    nodes = {n['id']: n for n in doc['nodes']}
    widgets(nodes[116], [HELP + '\n' + kind + ': ' + ('Upload both first and last frames.' if last else 'Upload the first frame; the last frame is disconnected.')], {})
    nodes[116]['title'] = 'Start here — ' + kind
    nodes[105]['widgets_values'][0] = PROMPT
    nodes[105]['widgets_values'][4] = 42
    nodes[105]['widgets_values_named'].update(prompt=PROMPT, noise_seed=42)
    nodes[105]['title'] = kind + ' — prompt, duration and models'
    widgets(nodes[114], [DEMO, 'image'], {'image': DEMO, 'upload': 'image'})
    nodes[114]['title'] = 'First frame — upload image'
    prefix = 'video/manual/AgentInfra_' + kind
    nodes[92]['widgets_values'][0] = prefix
    nodes[92]['widgets_values_named']['filename_prefix'] = prefix
    links = [v for v in doc['links'] if v[1] in nodes and v[3] in nodes]
    if last:
        image = copy.deepcopy(nodes[114])
        image.update(id=121, title='Last frame — upload image', pos=[-1610, 5560])
        doc['nodes'].append(image)
        links.append([229, 121, 0, 105, 1, 'IMAGE'])
    rebuild_links(doc, links)
    return doc


def reference_workflow():
    doc = read('source/video_minimax_h3_r2v.json')
    api = read('minimax_h3_ref2va_api.json')
    api['136']['inputs'].update(prompt=['138', 0], **{'ref_images.ref_image_0': ['137', 0]})
    api['137'] = {'class_type': 'LoadImage', 'inputs': {'image': DEMO}}
    api['138'] = {'class_type': 'PrimitiveStringMultiline', 'inputs': {'value': '参考 <Picture 1> 的人物和场景。' + PROMPT}}
    api['92']['inputs']['filename_prefix'] = 'video/manual/AgentInfra_Ref2VA'
    shift = next(n for n in read('source/video_minimax_h3_ref2v_lightx2v_turbo.json')['nodes'] if n['type'] == 'MiniMaxH3SigmaShift')
    shift.update(id=147, pos=[-800, 5160])
    doc['nodes'] = [n for n in doc['nodes'] if str(n['id']) in api or n['id'] == 116] + [shift]
    doc['extra'] = {'agent_infra_workflow': 'Ref2VA'}
    nodes = {n['id']: n for n in doc['nodes']}
    widgets(nodes[116], [HELP + '\nRef2VA: references guide identity/content, not fixed boundary frames. Connect more LoadImage nodes to ref_images; use <Picture 1>, <Picture 2>, etc. in connection order. Turbo v0.1: 4 steps, Euler/simple, video/audio shift 12/3, match reference sizing.'], {})
    nodes[116]['title'] = 'Start here — Ref2VA'
    nodes[137]['title'] = 'Reference 1 — upload image'
    links = []
    for key, entry in api.items():
        node = nodes[int(key)]
        named = dict(node.get('widgets_values_named') or {})
        # Preserve editor-only upload/seed controls and widget ordering.
        values = node.get('widgets_values') or []
        for index, name in enumerate(named):
            value = entry['inputs'].get(name)
            if value is not None and not isinstance(value, list):
                named[name] = value
                if index < len(values):
                    values[index] = value
        widgets(node, values, named)
        for name, value in entry['inputs'].items():
            if not isinstance(value, list):
                continue
            slot = next(i for i, p in enumerate(node['inputs']) if p['name'] == name)
            links.append([len(links) + 1, int(value[0]), value[1], int(key), slot, node['inputs'][slot]['type']])
    rebuild_links(doc, links)
    return doc


def build():
    target = ROOT / 'comfyui'
    target.mkdir(exist_ok=True)
    for name, graph in [('I2V - Turbo 4step 768P', frame_workflow(False)),
                        ('FL2V - Turbo 4step 768P', frame_workflow(True)),
                        ('Ref2VA - Turbo 4step 544P', reference_workflow())]:
        (target / (name + '.json')).write_text(json.dumps(graph, ensure_ascii=False, indent=2) + '\n')


def install(user_dir, input_dir, example):
    library = user_dir / 'default/workflows/Agent-Infra'
    library.mkdir(parents=True, exist_ok=True)
    for source in sorted((ROOT / 'comfyui').glob('*.json')):
        dest = library / source.name
        if dest.exists() and dest.read_bytes() != source.read_bytes():
            raise FileExistsError(f'Preserve your edited workflow by renaming it before reinstalling: {dest}')
        shutil.copyfile(source, dest)
        print(dest)
    if example:
        input_dir.mkdir(parents=True, exist_ok=True)
        dest = input_dir / DEMO
        if not dest.exists():
            shutil.copyfile(example, dest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--user-dir', type=Path)
    parser.add_argument('--input-dir', type=Path)
    parser.add_argument('--example-image', type=Path)
    args = parser.parse_args()
    if args.build:
        build()
    if args.user_dir:
        if args.example_image and not args.input_dir:
            parser.error('--example-image requires --input-dir')
        install(args.user_dir, args.input_dir, args.example_image)

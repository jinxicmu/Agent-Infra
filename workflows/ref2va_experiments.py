"""Separate experimental Ref2VA graphs; never changes the production manifest."""
import argparse
import copy
import json
from pathlib import Path
import shutil

from workflows.publish_comfyui import reference_workflow, rebuild_links, widgets

ROOT = Path(__file__).resolve().parent
VARIANTS = {
    'baseline': {'title': 'Previous LightX2V 4step', 'steps': 4,
                 'lora': 'minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors'},
    'lightx2v_8step': {
        'title': 'LightX2V 8step 768P', 'steps': 8,
        'lora': 'minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors'},
    'pai_8step': {'title': 'Alibaba PAI PDD 8step 768P', 'steps': 8,
                  'pdd': 'MiniMax-H3-Ref2VA-Acc-8Step.safetensors'},
    'singularity_4step': {
        'title': 'Singularity LightX2V 4step 768P', 'steps': 4,
        'lora': 'minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors',
        'model': 'Minimax-h3_Singularity_ref2va_Pruned_v1.3_int8.safetensors'},
}


def apply_variant(graph, variant):
    graph = copy.deepcopy(graph)
    spec = VARIANTS[variant]
    graph['124']['inputs']['steps'] = spec['steps']
    if 'model' in spec:
        graph['127']['inputs']['unet_name'] = spec['model']
    if 'lora' in spec:
        graph['145']['inputs']['lora_name'] = spec['lora']
    if 'pdd' in spec:
        del graph['145'], graph['124']
        graph['147']['inputs']['model'] = ['127', 0]
        graph['148'] = {'class_type': 'MiniMaxH3PDDAccApply', 'inputs': {
            'model': ['147', 0], 'pdd_file': spec['pdd'], 'nfe': '8',
            'lora_strength': 1.0, 'head_strength': 1.0, 'on_off_grid': 'error',
            'partition': '', 'enabled': True, 'partition_check': 'error'}}
        graph['126']['inputs']['model'] = ['148', 0]
        graph['125']['inputs']['sigmas'] = ['148', 1]
    return graph


def frontend(variant):
    spec = VARIANTS[variant]
    doc = reference_workflow()
    doc['extra']['agent_infra_workflow'] = 'Experimental Ref2VA ' + variant
    nodes = {n['id']: n for n in doc['nodes']}

    def set_value(node_id, name, value):
        node = nodes[node_id]
        named = node['widgets_values_named']
        node['widgets_values'][list(named).index(name)] = value
        named[name] = value

    set_value(124, 'steps', spec['steps'])
    set_value(115, 'megapixels', .98)
    set_value(115, 'aspect_ratio', '9:16 (Portrait Widescreen)')
    set_value(129, 'control_after_generate', 'fixed')
    set_value(92, 'filename_prefix', 'video/experiments/' + variant)
    if 'model' in spec:
        set_value(127, 'unet_name', spec['model'])
    if 'lora' in spec:
        set_value(145, 'lora_name', spec['lora'])
    case = ROOT.parent / 'tests/fixtures/h3_email_cases/case_1'
    set_value(138, 'value', (case / 'prompt.txt').read_text().rstrip('\n'))
    set_value(132, 'value', 4)
    set_value(137, 'image', 'h3_case_1_picture_1.png')
    links = list(doc['links'])
    for i, node_id in [(1, 149), (2, 150)]:
        node = copy.deepcopy(nodes[137])
        node.update(id=node_id, title=f'Picture {i+1} — reference image',
                    pos=[nodes[137]['pos'][0], nodes[137]['pos'][1] + 400 * i])
        node['widgets_values'][0] = f'h3_case_1_picture_{i+1}.png'
        node['widgets_values_named']['image'] = node['widgets_values'][0]
        doc['nodes'].append(node)
        slot = next(j for j, p in enumerate(nodes[136]['inputs'])
                    if p['name'] == f'ref_images.ref_image_{i}')
        links.append([max(x[0] for x in links)+1, node_id, 0, 136, slot, 'IMAGE'])
    if 'pdd' in spec:
        doc['nodes'] = [n for n in doc['nodes'] if n['id'] not in {124, 145}]
        links = [x for x in links if x[1] not in {124, 145} and x[3] not in {124, 145}
                 and not (x[3] == 126 and x[4] == 0)]
        node = {'id': 148, 'type': 'MiniMaxH3PDDAccApply', 'pos': [-800, 5500],
                'size': [400, 350], 'flags': {}, 'order': 10, 'mode': 0,
                'inputs': [{'name': 'model', 'type': 'MODEL', 'link': None},
                           {'name': 'bypass_sigmas', 'type': 'SIGMAS', 'link': None}],
                'outputs': [{'name': name, 'type': kind, 'links': None, 'slot_index': i}
                            for i, (name, kind) in enumerate([
                                ('model', 'MODEL'), ('sigmas', 'SIGMAS'), ('info', 'STRING')])],
                'properties': {'Node name for S&R': 'MiniMaxH3PDDAccApply'},
                'title': 'PAI PDD — full adapter and trained schedule'}
        values = {'pdd_file': spec['pdd'], 'nfe': '8', 'lora_strength': 1.,
                  'head_strength': 1., 'on_off_grid': 'error', 'partition': '',
                  'enabled': True, 'partition_check': 'error'}
        widgets(node, list(values.values()), values)
        doc['nodes'].append(node)
        for origin, slot, target, target_slot, kind in [
                (127, 0, 147, 0, 'MODEL'), (147, 0, 148, 0, 'MODEL'),
                (148, 0, 126, 0, 'MODEL'), (148, 1, 125, 3, 'SIGMAS')]:
            links.append([max(x[0] for x in links)+1, origin, slot, target, target_slot, kind])
    help_text = (f'## EXPERIMENTAL — {spec["title"]}\n'
                 'Uses email case 1. Replace the prompt, duration, and all three images for case 2.\n'
                 'Stop this GPU\'s pull-worker and wait for its task to finish before running.\n'
                 'Not enabled in the production API. Portrait 768P, native audio, fixed seed 42.\n'
                 'Picture 1 is a reference, not hard first-frame conditioning.\n'
                 'Video/audio sigma shifts 12/3. LightX2V 8-step retains existing Ref2VA shifts; '
                 'upstream has not documented a separate 8-step Ref2VA recipe.\n')
    widgets(nodes[116], [help_text], {})
    rebuild_links(doc, links)
    return doc


def build():
    target = ROOT / 'experiments/ref2va'
    target.mkdir(parents=True, exist_ok=True)
    source = json.loads((ROOT / 'minimax_h3_ref2va_api.json').read_text())
    for variant in VARIANTS:
        if variant == 'baseline':
            continue
        graph = apply_variant(source, variant)
        graph['115']['inputs'].update(megapixels=.98, aspect_ratio='9:16 (Portrait Widescreen)')
        (target / f'{variant}.api.json').write_text(json.dumps(graph, indent=2)+'\n')
        (target / f'{variant}.json').write_text(
            json.dumps(frontend(variant), ensure_ascii=False, indent=2)+'\n')


def install(user_dir, input_dir):
    library = user_dir / 'default/workflows/Agent-Infra/Experimental Ref2VA'
    library.mkdir(parents=True, exist_ok=True)
    input_dir.mkdir(parents=True, exist_ok=True)
    pairs = [(ROOT / 'experiments/ref2va' / f'{variant}.json',
              library / f'{variant}.json') for variant in VARIANTS if variant != 'baseline']
    for case in (1, 2):
        for source in (ROOT.parent / f'tests/fixtures/h3_email_cases/case_{case}').glob('*.png'):
            pairs.append((source, input_dir / f'h3_case_{case}_{source.name}'))
    for source, target in pairs:
        if target.exists() and source.read_bytes() != target.read_bytes():
            raise FileExistsError(f'Preserve your edited file before reinstalling: {target}')
        shutil.copyfile(source, target)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-dir', type=Path)
    parser.add_argument('--input-dir', type=Path)
    args = parser.parse_args()
    if bool(args.user_dir) != bool(args.input_dir):
        parser.error('--user-dir and --input-dir must be supplied together')
    build()
    if args.user_dir:
        install(args.user_dir, args.input_dir)

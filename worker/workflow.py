"""Task binding for the source-derived H3 Sage 41s execution graph."""
import copy
import json
from functools import lru_cache
from pathlib import Path

from worker.image_fetcher import fetch_image


@lru_cache(maxsize=8)
def _artifacts(workflow_dir: Path, revision: str, workflow_file: str, parameter_map: str):
    # Path + revision prevents unrelated deployments from sharing cached graphs.
    return (json.loads((workflow_dir / workflow_file).read_text()),
            json.loads((workflow_dir / parameter_map).read_text()))


def build_prompt_graph(assignment, settings, check=lambda: None) -> dict:
    manifest = settings.manifest
    template, binding = _artifacts(
        settings.workflow_dir.resolve(), manifest['revision'],
        manifest['workflow_file'], manifest['parameter_map'])
    graph = copy.deepcopy(template)
    req = assignment['request']
    content = req['content']
    texts = [item['text'] for item in content if item['type'] == 'text']
    images = [item for item in content if item['type'] == 'image_url']
    if len(texts) != 1 or not texts[0].strip():
        raise ValueError('H3 requires exactly one nonempty text prompt')
    roles = [item.get('role') for item in images]
    if roles.count('first_frame') != 1 or roles.count('last_frame') > 1 or any(
            role not in {'first_frame', 'last_frame'} for role in roles):
        raise ValueError('H3 requires one first_frame and at most one last_frame')
    if req['duration'] != manifest['duration'] or req['ratio'] != manifest['ratio']:
        raise ValueError('Request does not match this workflow duration/ratio')

    def bind(name, value):
        target = binding[name]
        graph[target['node']]['inputs'][target['input']] = value

    # Preserve dialogue, audio instructions, formatting, and reference tokens exactly.
    bind('prompt_target', texts[0])
    bind('duration_target', req['duration'])
    bind('seed_target', assignment['seed'])
    graph[binding['save_node']]['inputs']['filename_prefix'] = f"video/{assignment['task_id']}"
    by_role = {item['role']: item['image_url'] for item in images}
    for role in ('first_frame', 'last_frame'):
        if role not in by_role:
            target = binding[f'{role}_target']
            graph[target['node']]['inputs'].pop(target['input'], None)
            graph.pop(binding['image_nodes'][role], None)
            continue
        check()
        filename = fetch_image(by_role[role], assignment['task_id'], role, settings.input_dir, check)
        # Source connects LoadImage directly to H3; H3 owns image resizing.
        node_id = binding['image_nodes'][role]
        graph[node_id] = {'class_type': 'LoadImage', 'inputs': {'image': filename},
                          '_meta': {'title': f'Load Image ({role})'}}
        bind(f'{role}_target', [node_id, 0])
    return graph

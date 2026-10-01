"""Opt-in local ComfyUI measurement used by the email-case integration tests."""
import json
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit
import uuid


from worker.comfy_client import ComfyClient
from worker.gcs_uploader import validate_video
from workflows.parameters import validate_output


def measure(graph, request, variant, case_number, base_url, output_dir, gpu=0,
            timeout=2400):
    if urlsplit(base_url).hostname not in {'127.0.0.1', 'localhost', '::1'}:
        raise ValueError('Benchmarks require a local, reserved ComfyUI instance')
    client = ComfyClient(base_url.rstrip('/'))
    if client.queue():
        raise RuntimeError('ComfyUI queue must be empty before a benchmark')
    run_id = f'{variant}_case{case_number}_{uuid.uuid4().hex[:8]}'
    directory = Path(output_dir) / run_id
    directory.mkdir(parents=True, exist_ok=False)
    graph['92']['inputs']['filename_prefix'] = 'video/experiments/' + run_id
    (directory / 'prompt.json').write_text(json.dumps(graph, ensure_ascii=False, indent=2))
    report = {'variant': variant, 'case': case_number, 'seed': 42,
              'status': 'submitting', 'base_url': base_url, 'gpu_index': gpu,
              'requested_duration': request['duration'], 'resolution': request['resolution'],
              'ratio': request['ratio'], 'timing_scope': 'whole ComfyUI execution including model loading',
              'quality_review': 'pending; contract checks do not assess visual or spoken fidelity'}
    history = None
    samples = []
    start = time.monotonic()
    try:
        prompt_id = client.submit(graph, run_id)
        report.update(prompt_id=prompt_id, status='running')
        (directory / 'result.json').write_text(json.dumps(report, indent=2))
        while time.monotonic() - start < timeout:
            history = client.history(prompt_id)
            probe = subprocess.run([
                'nvidia-smi', f'--id={gpu}',
                '--query-gpu=memory.used,utilization.gpu', '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=10)
            if probe.returncode == 0:
                memory, utilization = map(int, probe.stdout.strip().split(','))
                samples.append({'seconds': round(time.monotonic()-start, 3),
                                'memory_mib': memory, 'utilization_percent': utilization})
            if history:
                break
            time.sleep(2)
        if not history:
            raise TimeoutError(f'Prompt {prompt_id} still pending; preserve the reserved GPU until it finishes')
        (directory / 'history.json').write_text(json.dumps(history, ensure_ascii=False, indent=2))
        status = history['status']
        if status['status_str'] != 'success':
            raise RuntimeError(f'ComfyUI failed: {status["messages"]}')
        messages = status['messages']
        if any(kind == 'execution_cached' and '125' in data.get('nodes', [])
               for kind, data in messages):
            raise RuntimeError('Sampler output was cached; this is not a valid performance measurement')
        stamps = {kind: data.get('timestamp') for kind, data in messages}
        if stamps.get('execution_success') and stamps.get('execution_start'):
            report['execution_seconds'] = (stamps['execution_success']-stamps['execution_start'])/1000
        media = [item for output in history['outputs'].values()
                 for value in output.values() if isinstance(value, list)
                 for item in value if isinstance(item, dict)
                 and item.get('filename', '').lower().endswith('.mp4')]
        if len(media) != 1:
            raise RuntimeError(f'Expected one MP4, found {len(media)}')
        item = media[0]
        video = directory / 'output.mp4'
        with client.session.get(client.base+'/view', params={
                'filename': item['filename'], 'subfolder': item.get('subfolder', ''),
                'type': item.get('type', 'output')}, stream=True, timeout=(5, 60)) as response:
            response.raise_for_status()
            with video.open('wb') as stream:
                for chunk in response.iter_content(1024**2):
                    stream.write(chunk)
        output = validate_video(video)
        validate_output(output, request['resolution'], request['ratio'], request['duration'])
        report.update(status='passed', output=output, video=str(video.resolve()),
                      output_bytes=video.stat().st_size)
    except Exception as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        report['wall_seconds'] = round(time.monotonic()-start, 3)
        report['sampled_peak_vram_mib'] = max((s['memory_mib'] for s in samples), default=None)
        (directory / 'gpu_samples.json').write_text(json.dumps(samples, indent=2))
        (directory / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(f'Benchmark evidence: {directory.resolve()}', flush=True)
    return report

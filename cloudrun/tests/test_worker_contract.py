"""Exercise the real worker HTTP protocol against the API and Firestore emulator."""
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock
from fastapi.testclient import TestClient
from cloudrun.main import create_app
from worker.cloud_client import CloudClient
from worker.journal import Journal
from worker.runner import Runner


def test_worker_finishes_task_through_real_api_contract(store, settings, request_body, tmp_path, monkeypatch):
    output = tmp_path/'output'
    output.mkdir()
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=size=32x32:rate=1',
                    '-t', '1', '-c:v', 'libx264', str(output/'sample.mp4')], check=True)
    verifier = Mock()
    verifier.verify.return_value = {'gcs_generation':'999', 'checksum':{'algorithm':'crc32c','value':'AAAAAA=='}}
    with TestClient(create_app(settings, store, verifier)) as api:
        class Session:
            def __init__(self):
                self.headers = {}
            def post(self, url, json, **kwargs):
                return api.post(url.removeprefix('https://cloud.test'), json=json, headers=self.headers)
        monkeypatch.setattr('worker.cloud_client.requests.Session', Session)
        local = SimpleNamespace(worker_id='worker-a', cloud_url='https://cloud.test', api_key=settings.workers['worker-a'],
            manifest={'revision':settings.revision,'save_node':'92'}, poll_seconds=0.01,
            state_dir=tmp_path/'state', input_dir=tmp_path/'input', output_dir=output, min_free_bytes=0)
        local.input_dir.mkdir()
        comfy = Mock()
        comfy.queue.return_value = []
        comfy.submit.return_value = 'prompt-123'
        comfy.history.return_value = {'status':{'completed':True},
            'outputs':{'92':{'videos':[{'filename':'sample.mp4'}]}}}
        uploader = Mock()
        uploader.upload.return_value = {'generation':'999'}
        monkeypatch.setattr('worker.runner.build_prompt_graph', lambda *args: {'approved':'graph'})
        task = store.create(request_body, 'client-a')
        runner = Runner(local, CloudClient(local), comfy, Journal(local.state_dir), uploader)
        assert runner.prepare_assignment()
        runner.start_heartbeat()
        try:
            runner.execute()
        finally:
            runner.stop_heartbeat()
        assert store.get(task['task_id'])['status'] == 'succeeded'
        assert runner.record is None
        comfy.submit.assert_called_once()
        verifier.verify.assert_called_once()

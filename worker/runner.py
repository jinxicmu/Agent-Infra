import hashlib
import json
import logging
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests
from worker.cloud_client import CloudError
from worker.image_fetcher import InputError
from worker.workflow import build_prompt_graph
from worker.gcs_uploader import validate_video

logger = logging.getLogger(__name__)


class LeaseLost(Exception):
    pass


class ExecutionFailure(Exception):
    def __init__(self, code):
        self.code = code


class Runner:
    def __init__(self, settings, cloud, comfy, journal, uploader):
        self.s, self.cloud, self.comfy, self.journal, self.uploader = settings, cloud, comfy, journal, uploader
        self.record = journal.read()
        self.lock = threading.RLock()
        self.lost = threading.Event()
        self.heartbeat_stop = threading.Event()
        self.shutdown = threading.Event()
        self.deadline = 0
        self.heartbeat_thread = None

    def save(self, **updates):
        with self.lock:
            self.record.update(updates)
            self.journal.write(self.record)

    def clear(self):
        self.journal.clear()
        self.record = None

    def accept(self, task):
        if task.get('worker_id') != self.s.worker_id:
            raise CloudError(409, 'LEASE_CONFLICT')
        if task.get('workflow_revision') != self.s.manifest['revision']:
            raise CloudError(409, 'WORKFLOW_REVISION_MISMATCH')
        # Server time avoids dependence on workstation clock skew; reserve one HTTP timeout.
        remaining = (datetime.fromisoformat(task['lease_deadline']) -
                     datetime.fromisoformat(task['server_time'])).total_seconds()
        with self.lock:
            self.deadline = time.monotonic() + max(0, remaining - 20)
            self.record['task'] = task
            self.journal.write(self.record)

    def check(self):
        if self.lost.is_set() or time.monotonic() >= self.deadline:
            self.lost.set()
            raise LeaseLost()

    def _heartbeat(self):
        while not self.heartbeat_stop.is_set():
            try:
                self.check()
                with self.lock:
                    task = dict(self.record['task'])
                    phase = self.record.get('phase', 'leased')
                    prompt_id = self.record.get('prompt_id')
                result = self.cloud.task(task, 'heartbeat', phase=phase, comfy_prompt_id=prompt_id)
                self.accept(result)
            except LeaseLost:
                return
            except CloudError as exc:
                if exc.status < 500 and exc.status != 429:
                    self.lost.set()
                    return
            except requests.RequestException:
                pass
            except Exception:
                logger.exception('Heartbeat/journal failed')
                self.lost.set()
                return
            self.heartbeat_stop.wait(self.s.poll_seconds)

    def start_heartbeat(self):
        self.lost.clear()
        self.heartbeat_stop.clear()
        self.heartbeat_thread = threading.Thread(target=self._heartbeat, name='lease-renewal', daemon=True)
        self.heartbeat_thread.start()

    def stop_heartbeat(self):
        self.heartbeat_stop.set()
        if self.heartbeat_thread:
            self.heartbeat_thread.join(timeout=25)

    def drain(self):
        # Do not accept another task until this dedicated instance is demonstrably empty.
        while True:
            try:
                if not self.comfy.queue():
                    return
                self.comfy.interrupt()
            except requests.RequestException:
                logger.warning('Waiting for dedicated ComfyUI to drain')
            time.sleep(self.s.poll_seconds)

    def prepare_assignment(self):
        if self.record and self.record.get('terminal'):
            # A result response could have been lost just before the process exited.
            try:
                self.deliver_terminal(check_lease=False)
                return False
            except CloudError as exc:
                if exc.code not in ('LEASE_CONFLICT',):
                    raise
                # A previous recovery response may have been lost; replay persisted proof below.
        if self.record and self.record.get('task'):
            task = self.record['task']
            proof = self.record.get('recovery')
            if not proof:
                proof = {'task_id': task['task_id'], 'lease_token': task['lease_token'],
                         'old_worker_session_id': task['worker_session_id'],
                         'new_worker_session_id': uuid.uuid4().hex}
                self.save(recovery=proof)
            self.accept(self.cloud.recover(proof))
            self.save(recovery=None)
            return True
        if self.record is None:
            if shutil.disk_usage(self.s.output_dir).free < self.s.min_free_bytes:
                logger.warning('Insufficient output disk space; refusing claim')
                return False
            if self.comfy.queue():
                logger.warning('ComfyUI has unjournaled work; refusing claim')
                return False
            self.record = {'claim_session': uuid.uuid4().hex}
            self.journal.write(self.record)  # Survives a lost claim response.
        task = self.cloud.claim(self.record['claim_session'])
        if task is None:
            self.clear()
            return False
        self.accept(task)
        return True

    def execute(self):
        task = self.record['task']
        if self.record.get('terminal'):
            return self.deliver_terminal()
        if not self.record.get('prompt_id'):
            if self.record.get('submission_intent'):
                prompt_id = self.comfy.reconcile(task['task_id'])
                if not prompt_id:
                    self.drain()
                    raise ExecutionFailure('SUBMISSION_UNCERTAIN')
            else:
                if self.comfy.queue():
                    raise ExecutionFailure('SUBMISSION_UNCERTAIN')
                try:
                    graph = build_prompt_graph(task, self.s, self.check)
                except LeaseLost:
                    raise
                except Exception as exc:
                    raise ExecutionFailure('INVALID_REQUEST') from exc
                self.check()
                self.save(submission_intent=True,
                          graph_hash=hashlib.sha256(json.dumps(graph, sort_keys=True).encode()).hexdigest())
                try:
                    prompt_id = self.comfy.submit(graph, task['task_id'])
                except Exception:
                    # Never retry /prompt after an ambiguous network response.
                    prompt_id = self.comfy.reconcile(task['task_id'])
                    if not prompt_id:
                        self.drain()
                        raise ExecutionFailure('SUBMISSION_UNCERTAIN')
            self.save(prompt_id=prompt_id, phase='running')
        while not self.record.get('output'):
            self.check()
            history = self.comfy.history(self.record['prompt_id'])
            if history:
                status = history.get('status', {})
                if status.get('status_str') == 'error':
                    raise ExecutionFailure('INFERENCE_FAILED')
                if status.get('completed'):
                    outputs = history.get('outputs', {}).get(self.s.manifest['save_node'], {})
                    videos = outputs.get('videos') or outputs.get('gifs') or outputs.get('images') or []
                    if not videos:
                        raise ExecutionFailure('INFERENCE_FAILED')
                    video = videos[0]
                    path = (self.s.output_dir / video.get('subfolder', '') / video['filename']).resolve()
                    if not path.is_relative_to(self.s.output_dir.resolve()):
                        raise ExecutionFailure('INFERENCE_FAILED')
                    try:
                        validate_video(path)
                    except Exception as exc:
                        raise ExecutionFailure('INFERENCE_FAILED') from exc
                    self.save(output=str(path), phase='uploading')
                    break
            time.sleep(self.s.poll_seconds)
        for attempt in range(3):
            self.check()
            try:
                artifact = self.uploader.upload(Path(self.record['output']), task, self.check)
                self.save(artifact=artifact)
                break
            except LeaseLost:
                raise
            except Exception:
                if attempt == 2:
                    raise ExecutionFailure('GCS_UPLOAD_FAILED')
                time.sleep(self.s.poll_seconds)
        self.save(terminal={'action': 'complete'})
        self.deliver_terminal()

    def deliver_terminal(self, check_lease=True):
        while True:
            if check_lease:
                self.check()
            terminal = self.record['terminal']
            try:
                self.cloud.task(self.record['task'], terminal['action'],
                                **{k: v for k, v in terminal.items() if k != 'action'})
                # Stop renewal before removing the journal; a concurrent terminal response is harmless.
                self.stop_heartbeat()
                self.drain()
                self.clear()
                return
            except CloudError as exc:
                if exc.code == 'RESULT_VERIFICATION_FAILED' and terminal['action'] == 'complete':
                    self.save(terminal={'action': 'fail', 'code': 'RESULT_VERIFICATION_FAILED'})
                    continue
                if exc.code in ('WORKER_LEASE_EXPIRED', 'TASK_DEADLINE_EXCEEDED', 'TASK_ALREADY_TERMINAL'):
                    self.stop_heartbeat()
                    self.drain()
                    self.clear()
                    return
                if exc.status < 500 and exc.status != 429:
                    raise
            except requests.RequestException:
                pass
            if not check_lease:
                # Allow the outer retry loop to remain responsive during startup outages.
                raise requests.ConnectionError('Terminal acknowledgement pending')
            time.sleep(self.s.poll_seconds)

    def cleanup(self):
        # Only worker-owned gen_* files; never remove an active task's artifacts.
        active = (self.record or {}).get('task', {}).get('task_id')
        cutoff = time.time() - 86400
        for directory in (self.s.input_dir, self.s.output_dir):
            for path in directory.rglob('gen_*'):
                if path.is_file() and not path.is_symlink() and (not active or not path.name.startswith(active)):
                    if path.stat().st_mtime < cutoff:
                        path.unlink()

    def run(self):
        while not self.shutdown.is_set():
            try:
                self.cleanup()
                if not self.prepare_assignment():
                    self.shutdown.wait(self.s.poll_seconds)
                    continue
                self.start_heartbeat()
                try:
                    self.execute()
                except ExecutionFailure as exc:
                    self.save(terminal={'action': 'fail', 'code': exc.code})
                    self.deliver_terminal()
                finally:
                    self.stop_heartbeat()
            except LeaseLost:
                self.stop_heartbeat()
                self.drain()
                # Retain proof: recovery/terminal delivery will obtain the definitive cloud outcome.
            except CloudError as exc:
                logger.warning('Worker API: %s', exc.code)
                if exc.code in ('WORKER_LEASE_EXPIRED', 'TASK_DEADLINE_EXCEEDED', 'TASK_ALREADY_TERMINAL'):
                    self.drain()
                    self.clear()
                elif exc.status in (401, 403) or exc.code in ('LEASE_CONFLICT', 'WORKFLOW_REVISION_MISMATCH'):
                    # Operator intervention required; systemd may retry without losing the journal.
                    raise
            except requests.RequestException:
                logger.warning('Connection unavailable; preserving current journal')
            self.shutdown.wait(self.s.poll_seconds)

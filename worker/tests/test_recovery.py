import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import requests
from worker.journal import Journal
from worker.runner import Runner, ExecutionFailure, LeaseLost


def task():
    now = datetime.now(timezone.utc)
    return {'task_id': 'gen_' + '1'*32, 'lease_token': 'secret-token', 'worker_session_id': 'old',
            'worker_id': 'worker-a', 'workflow_revision': 'revision', 'lease_deadline': (now+timedelta(seconds=120)).isoformat(),
            'server_time': now.isoformat(), 'seed': 1}


@pytest.fixture
def runner(tmp_path):
    settings = SimpleNamespace(worker_id='worker-a', state_dir=tmp_path, input_dir=tmp_path/'input', output_dir=tmp_path/'output',
                               min_free_bytes=0, poll_seconds=0.001, manifest={'save_node':'92', 'revision':'revision'})
    settings.input_dir.mkdir()
    settings.output_dir.mkdir()
    cloud, comfy, uploader = Mock(), Mock(), Mock()
    comfy.queue.return_value = []
    return Runner(settings, cloud, comfy, Journal(tmp_path), uploader)


def test_journal_lock_excludes_duplicate_worker(tmp_path):
    journal = Journal(tmp_path)
    journal.write({'task': 'persisted'})
    assert journal.read() == {'task': 'persisted'}
    with pytest.raises(BlockingIOError):
        Journal(tmp_path)


def test_lost_claim_response_reuses_persisted_session(runner):
    runner.cloud.claim.side_effect = [requests.ConnectionError(), task()]
    with pytest.raises(requests.ConnectionError):
        runner.prepare_assignment()
    saved = runner.journal.read()['claim_session']
    runner.prepare_assignment()
    assert runner.cloud.claim.call_args_list[0].args == (saved,)
    assert runner.cloud.claim.call_args_list[1].args == (saved,)


def test_recovery_response_loss_replays_exact_proof(runner):
    runner.record = {'task': task(), 'prompt_id': 'existing'}
    runner.journal.write(runner.record)
    runner.cloud.recover.side_effect = [requests.ConnectionError(), {**task(), 'worker_session_id':'new'}]
    with pytest.raises(requests.ConnectionError):
        runner.prepare_assignment()
    assert runner.journal.read()['recovery']['old_worker_session_id'] == 'old'
    runner.prepare_assignment()
    assert runner.cloud.recover.call_args_list[0] == runner.cloud.recover.call_args_list[1]
    runner.comfy.submit.assert_not_called()


def test_known_prompt_resumes_without_submission(runner, monkeypatch):
    runner.record = {'task': task(), 'prompt_id': 'known', 'phase':'running'}
    runner.accept(runner.record['task'])
    runner.comfy.history.return_value = {'status': {'completed': True},
        'outputs': {'92': {'videos': [{'filename':'video.mp4'}]}}}
    monkeypatch.setattr('worker.runner.validate_video', lambda _: None)
    runner.uploader.upload.return_value = {'generation':'123'}
    runner.cloud.task.return_value = {'status':'succeeded'}
    runner.execute()
    runner.comfy.submit.assert_not_called()
    runner.comfy.history.assert_called_once_with('known')
    assert runner.journal.read() is None


def test_ambiguous_submission_never_resubmits(runner):
    runner.record = {'task': task(), 'submission_intent': True}
    runner.accept(runner.record['task'])
    runner.comfy.reconcile.return_value = None
    with pytest.raises(ExecutionFailure) as error:
        runner.execute()
    assert error.value.code == 'SUBMISSION_UNCERTAIN'
    runner.comfy.submit.assert_not_called()


def test_lost_completion_response_retries_outbox_without_render(runner):
    runner.record = {'task': task(), 'terminal': {'action': 'complete'}}
    runner.accept(runner.record['task'])
    runner.cloud.task.side_effect = [requests.ConnectionError(), {'status':'succeeded'}]
    runner.deliver_terminal()
    assert runner.cloud.task.call_count == 2
    runner.comfy.submit.assert_not_called()
    assert runner.record is None


def test_local_lease_expiry_stops_execution(runner):
    runner.record = {'task': task(), 'prompt_id': 'known'}
    runner.deadline = time.monotonic()-1
    with pytest.raises(LeaseLost):
        runner.execute()
    runner.comfy.history.assert_not_called()


def test_foreign_output_path_cannot_be_uploaded(runner):
    runner.record = {'task': task(), 'prompt_id': 'known'}
    runner.accept(runner.record['task'])
    runner.comfy.history.return_value = {'status': {'completed': True},
        'outputs': {'92': {'videos': [{'filename':'../outside.mp4'}]}}}
    with pytest.raises(ExecutionFailure):
        runner.execute()
    runner.uploader.upload.assert_not_called()

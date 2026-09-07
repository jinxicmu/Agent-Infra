from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import pytest
from cloudrun.errors import ApiError


def proof(task, **extra):
    return {key: task[key] for key in ('worker_session_id', 'lease_token', 'workflow_revision')} | extra


def recover_proof(task, new='new-session'):
    return {'task_id': task['task_id'], 'lease_token': task['lease_token'],
            'old_worker_session_id': task['worker_session_id'], 'new_worker_session_id': new,
            'workflow_revision': task['workflow_revision']}


def test_priority_and_fifo(store, request_body):
    batch = store.create({**request_body, 'mode': 'batch'}, 'client-a')
    realtime = store.create(request_body, 'client-a')
    next_realtime = store.create(request_body, 'client-a')
    a = store.claim('worker-a', 'session-a', store.s.revision)
    b = store.claim('worker-b', 'session-b', store.s.revision)
    assert a['task_id'] == realtime['task_id']
    assert b['task_id'] == next_realtime['task_id']
    assert store.get(batch['task_id'])['status'] == 'queued'


def test_two_workers_cannot_own_one_task(store, request_body):
    store.create(request_body, 'client-a')
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda worker: store.claim(worker, worker, store.s.revision), ['worker-a', 'worker-b']))
    assert sum(result is not None for result in results) == 1


def test_retried_claim_same_worker_cannot_lease_two_tasks(store, request_body):
    for _ in range(2):
        store.create(request_body, 'client-a')
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: store.claim('worker-a', 'session-a', store.s.revision), range(2)))
    assert results[0]['task_id'] == results[1]['task_id']
    assert results[0]['lease_token'] == results[1]['lease_token']
    assert len(list(store.pending('realtime').stream())) == 1


def test_two_tasks_concurrently_go_to_distinct_workers(store, request_body):
    for _ in range(2):
        store.create(request_body, 'client-a')
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda worker: store.claim(worker, worker, store.s.revision), ['worker-a', 'worker-b']))
    assert len({task['task_id'] for task in results}) == 2


def test_idempotent_creation_and_conflict(store, request_body):
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: store.create(request_body, 'client-a', 'same-key'), range(2)))
    assert results[0]['task_id'] == results[1]['task_id']
    with pytest.raises(ApiError, match='Idempotency conflict'):
        store.create({**request_body, 'mode': 'batch'}, 'client-a', 'same-key')


def test_recovery_fences_old_process_and_is_retryable(store, request_body):
    store.create(request_body, 'client-a')
    task = store.claim('worker-a', 'old-session', store.s.revision)
    body = recover_proof(task)
    recovered = store.recover('worker-a', body)
    assert recovered['worker_session_id'] == 'new-session'
    assert store.recover('worker-a', body)['lease_token'] == task['lease_token']
    with pytest.raises(ApiError) as error:
        store.mutate(task['task_id'], 'worker-a', proof(task), 'heartbeat')
    assert error.value.code == 'LEASE_CONFLICT'
    with pytest.raises(ApiError):
        store.recover('worker-a', recover_proof(task, 'competing-session'))


def test_expired_recovery_commits_failure_before_error(store, request_body):
    store.create(request_body, 'client-a')
    task = store.claim('worker-a', 'old-session', store.s.revision)
    store.clock = lambda: task['lease_deadline'] + timedelta(seconds=1)
    for _ in range(2):
        with pytest.raises(ApiError) as error:
            store.recover('worker-a', recover_proof(task))
        assert error.value.code == 'WORKER_LEASE_EXPIRED'
        assert store.get(task['task_id'])['status'] == 'failed'
    assert store.workers.document('worker-a').get().to_dict()['task_id'] is None
    assert store.claim('worker-b', 'b', store.s.revision) is None


def test_hard_deadline_cannot_be_renewed(store, request_body):
    store.create(request_body, 'client-a')
    task = store.claim('worker-a', 'old-session', store.s.revision)
    store.clock = lambda: task['execution_deadline'] + timedelta(seconds=1)
    with pytest.raises(ApiError) as error:
        store.mutate(task['task_id'], 'worker-a', proof(task), 'heartbeat')
    assert error.value.code == 'TASK_DEADLINE_EXCEEDED'
    assert store.get(task['task_id'])['status'] == 'failed'


def test_complete_retry_does_not_clear_new_assignment(store, request_body):
    store.create(request_body, 'client-a')
    task = store.claim('worker-a', 'a', store.s.revision)
    result = {'gcs_generation': '123', 'checksum': {'algorithm': 'crc32c', 'value': 'AAAAAA=='}}
    store.mutate(task['task_id'], 'worker-a', proof(task), 'complete', result)
    store.create(request_body, 'client-a')
    new = store.claim('worker-a', 'a', store.s.revision)
    assert store.mutate(task['task_id'], 'worker-a', proof(task), 'complete', result)['status'] == 'succeeded'
    assert store.workers.document('worker-a').get().to_dict()['task_id'] == new['task_id']


def test_sweep_works_without_workers_and_never_requeues(store, request_body):
    store.create(request_body, 'client-a')
    task = store.claim('worker-a', 'a', store.s.revision)
    store.clock = lambda: task['lease_deadline'] + timedelta(seconds=1)
    assert store.sweep() == 1
    assert store.sweep() == 0
    assert store.get(task['task_id'])['status'] == 'failed'


def test_wrong_revision_cannot_claim(store, request_body):
    task = store.create(request_body, 'client-a')
    with pytest.raises(ApiError) as error:
        store.claim('worker-a', 'a', 'wrong')
    assert error.value.code == 'WORKFLOW_REVISION_MISMATCH'
    assert store.get(task['task_id'])['status'] == 'queued'


def test_soft_admission_and_idempotency_before_rejection(store, request_body):
    store.s.realtime_limit = 1
    task = store.create(request_body, 'client-a', 'same')
    assert store.create(request_body, 'client-a', 'same')['task_id'] == task['task_id']
    with pytest.raises(ApiError) as error:
        store.create(request_body, 'client-a', 'different')
    assert (error.value.status, error.value.code) == (429, 'QUEUE_FULL')


def test_heartbeat_racing_recovery_cannot_restore_old_session(store, request_body):
    store.create(request_body, 'client-a')
    task = store.claim('worker-a', 'old', store.s.revision)
    def heartbeat():
        try:
            return store.mutate(task['task_id'], 'worker-a', proof(task, phase='running'), 'heartbeat')
        except ApiError as error:
            assert error.code == 'LEASE_CONFLICT'
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(heartbeat)
        b = pool.submit(store.recover, 'worker-a', recover_proof(task))
        a.result()
        b.result()
    assert store.get(task['task_id'])['worker_session_id'] == 'new-session'
    assert store.workers.document('worker-a').get().to_dict()['worker_session_id'] == 'new-session'


def test_success_cannot_publish_after_expiry(store, request_body):
    store.create(request_body, 'client-a')
    task = store.claim('worker-a', 'a', store.s.revision)
    store.clock = lambda: task['lease_deadline'] + timedelta(seconds=1)
    with pytest.raises(ApiError) as error:
        store.mutate(task['task_id'], 'worker-a', proof(task), 'complete', {'gcs_generation':'123'})
    assert error.value.code == 'WORKER_LEASE_EXPIRED'
    assert store.get(task['task_id'])['gcs_generation'] is None

"""Firestore is the queue. Transactions never perform inference or GCS calls."""
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from cloudrun.errors import ApiError

ACTIVE = ('leased', 'running', 'uploading')
EXPIRY = ('WORKER_LEASE_EXPIRED', 'TASK_DEADLINE_EXCEEDED')


def utcnow():
    return datetime.now(timezone.utc)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class TaskStore:
    def __init__(self, db, settings, clock=utcnow):
        self.db, self.s, self.clock = db, settings, clock
        self.tasks = db.collection('tasks')
        self.workers = db.collection('workers')

    def transaction(self, fn):
        try:
            result = firestore.transactional(fn)(self.db.transaction(max_attempts=5))
        except ValueError as exc:
            if 'attempts' in str(exc):
                raise ApiError(503, 'QUEUE_UNAVAILABLE') from exc
            raise
        # Expiry errors are returned from the callback: their writes MUST commit.
        if isinstance(result, ApiError):
            raise result
        return result

    def get(self, task_id):
        value = self.tasks.document(task_id).get().to_dict()
        if not value:
            raise ApiError(404, 'TASK_NOT_FOUND')
        return value

    def pending(self, mode):
        return self.tasks.where(filter=FieldFilter('status', '==', 'queued')).where(
            filter=FieldFilter('mode', '==', mode))

    def create(self, request, client, key=None):
        task_id = 'gen_' + uuid.uuid4().hex
        ref = self.tasks.document(task_id)
        fingerprint = digest(request)
        idem = self.db.collection('idempotency').document(digest([client, key])) if key else None
        # Soft thresholds intentionally do not introduce a shared queue counter.
        counts = {m: self.pending(m).count().get()[0][0].value for m in ('realtime', 'batch')}
        seed = secrets.randbits(32)
        def create(tx):
            now = self.clock()
            previous = idem.get(transaction=tx).to_dict() if idem else None
            if previous and previous['expires_at'] > now:
                if previous['fingerprint'] != fingerprint:
                    raise ApiError(409, 'IDEMPOTENCY_CONFLICT')
                return previous['task_id']
            if counts[request['mode']] >= getattr(self.s, request['mode'] + '_limit') or sum(counts.values()) >= self.s.total_limit:
                raise ApiError(429, 'QUEUE_FULL')
            # Per-client admission rate is separate from queue membership.
            rate = self.db.collection('client_rates').document(digest(client))
            previous_rate = rate.get(transaction=tx).to_dict() or {}
            window = int(now.timestamp()) // 60
            used = previous_rate.get('count', 0) if previous_rate.get('window') == window else 0
            if used >= self.s.client_rpm:
                raise ApiError(429, 'RATE_LIMITED')
            task = dict(task_id=task_id, request=request, client_id=client, model=request['model'],
                        workflow_type=('fl2v' if any(c.get('role') == 'last_frame' and c['type'] == 'image_url'
                                                    for c in request['content']) else 'i2v_first'),
                        mode=request['mode'], status='queued',
                        created_at=firestore.SERVER_TIMESTAMP, updated_at=firestore.SERVER_TIMESTAMP,
                        worker_id=None, worker_session_id=None, lease_token=None, lease_deadline=None,
                        seed=seed, workflow_revision=self.s.revision, gcs_generation=None, checksum=None,
                        gcs_bucket=self.s.bucket, gcs_object=f'{self.s.prefix}/{task_id}.mp4',
                        error=None, comfy_prompt_id=None)
            tx.create(ref, task)
            tx.set(rate, {'window': window, 'count': used + 1})
            if idem:
                tx.set(idem, {'task_id': task_id, 'fingerprint': fingerprint,
                              'expires_at': now + timedelta(days=7)})
            return task_id
        return self.get(self.transaction(create))

    def _revision(self, revision):
        if revision != self.s.revision:
            raise ApiError(409, 'WORKFLOW_REVISION_MISMATCH')

    def _expired(self, task):
        if task['status'] not in ACTIVE:
            return None
        now = self.clock()
        if task['execution_deadline'] <= now:
            return 'TASK_DEADLINE_EXCEEDED'
        if task['lease_deadline'] <= now:
            return 'WORKER_LEASE_EXPIRED'
        return None

    def _terminal(self, tx, task, guard, changes):
        changes.update(updated_at=firestore.SERVER_TIMESTAMP, finished_at=firestore.SERVER_TIMESTAMP,
                       expires_at=self.clock() + timedelta(days=7))
        tx.update(self.tasks.document(task['task_id']), changes)
        if guard and guard.get('task_id') == task['task_id'] and guard.get('worker_session_id') == task['worker_session_id']:
            tx.set(self.workers.document(task['worker_id']), {'task_id': None})

    def _expire(self, tx, task, guard):
        code = self._expired(task)
        if code:
            self._terminal(tx, task, guard, {'status': 'failed', 'error': {'code': code, 'message': code}})
            return ApiError(409, code)
        return None

    def claim(self, worker, session, revision):
        self._revision(revision)
        guard_ref = self.workers.document(worker)
        def claim(tx):
            guard = guard_ref.get(transaction=tx).to_dict() or {}
            if guard.get('task_id'):
                task = self.tasks.document(guard['task_id']).get(transaction=tx).to_dict()
                if not task:
                    raise ApiError(409, 'LEASE_CONFLICT')
                expiry = self._expire(tx, task, guard)
                if expiry:
                    return expiry
                if task['worker_session_id'] != session or task['status'] not in ACTIVE:
                    raise ApiError(409, 'LEASE_CONFLICT')
                return task
            selected = []
            for mode in ('realtime', 'batch'):
                query = self.pending(mode).order_by('created_at').order_by('__name__').limit(1)
                selected = list(query.stream(transaction=tx))
                if selected:
                    break
            if not selected:
                return None
            task = selected[0].to_dict()
            self._revision(task['workflow_revision'])
            now = self.clock()
            changes = dict(status='leased', worker_id=worker, worker_session_id=session,
                           lease_token=secrets.token_urlsafe(32),
                           lease_deadline=now + timedelta(seconds=self.s.lease_seconds),
                           execution_deadline=now + timedelta(seconds=self.s.task_seconds),
                           leased_at=now, updated_at=now)
            tx.update(selected[0].reference, changes)
            tx.set(guard_ref, {'task_id': task['task_id'], 'worker_session_id': session})
            return {**task, **changes}
        return self.transaction(claim)

    def _read_owned(self, tx, task_id, worker, session, token):
        task = self.tasks.document(task_id).get(transaction=tx).to_dict()
        if not task:
            raise ApiError(404, 'TASK_NOT_FOUND')
        if (task['worker_id'], task['worker_session_id'], task['lease_token']) != (worker, session, token):
            raise ApiError(409, 'LEASE_CONFLICT')
        guard = self.workers.document(worker).get(transaction=tx).to_dict() or {}
        if task['status'] in ACTIVE and (guard.get('task_id'), guard.get('worker_session_id')) != (task_id, session):
            raise ApiError(409, 'LEASE_CONFLICT')
        return task, guard

    def mutate(self, task_id, worker, proof, action, result=None):
        self._revision(proof['workflow_revision'])
        def mutate(tx):
            task, guard = self._read_owned(tx, task_id, worker, proof['worker_session_id'], proof['lease_token'])
            if task['status'] not in ACTIVE:
                if action in ('complete', 'check') and task['status'] == 'succeeded':
                    return task
                if action == 'fail' and task['status'] == 'failed' and task['error']['code'] == proof['code']:
                    return task
                code = (task.get('error') or {}).get('code')
                raise ApiError(409, code if code in EXPIRY else 'TASK_ALREADY_TERMINAL')
            expiry = self._expire(tx, task, guard)
            if expiry:
                return expiry
            if action == 'check':
                return task
            if action == 'heartbeat':
                ranks = {'leased': 0, 'running': 1, 'uploading': 2}
                phase = proof.get('phase', 'leased')
                changes = {'lease_deadline': min(self.clock() + timedelta(seconds=self.s.lease_seconds), task['execution_deadline']),
                           'updated_at': self.clock()}
                if ranks[phase] >= ranks[task['status']]:
                    changes['status'] = phase
                if phase == 'running' and not task.get('started_at'):
                    changes['started_at'] = self.clock()
                if phase == 'uploading' and not task.get('uploading_at'):
                    changes['uploading_at'] = self.clock()
                prompt = proof.get('comfy_prompt_id')
                if prompt:
                    if task.get('comfy_prompt_id') not in (None, prompt):
                        raise ApiError(409, 'LEASE_CONFLICT')
                    changes['comfy_prompt_id'] = prompt
                tx.update(self.tasks.document(task_id), changes)
            elif action == 'complete':
                now = self.clock()
                started = task.get('started_at', task['leased_at'])
                uploading = task.get('uploading_at', now)
                changes = {'status': 'succeeded', **result, 'metrics': {
                    'queue_time_ms': max(0, int((started-task['created_at']).total_seconds()*1000)),
                    'inference_time_ms': max(0, int((uploading-started).total_seconds()*1000)),
                    'upload_time_ms': max(0, int((now-uploading).total_seconds()*1000)),
                    'total_time_ms': max(0, int((now-task['created_at']).total_seconds()*1000))}}
                self._terminal(tx, task, guard, changes)
            elif action == 'fail':
                changes = {'status': 'failed', 'error': {'code': proof['code'], 'message': proof['code']}}
                self._terminal(tx, task, guard, changes)
            else:
                raise ValueError(action)
            return {**task, **changes}
        return self.transaction(mutate)

    def recover(self, worker, proof):
        self._revision(proof['workflow_revision'])
        def recover(tx):
            ref = self.tasks.document(proof['task_id'])
            task = ref.get(transaction=tx).to_dict()
            if not task:
                raise ApiError(404, 'TASK_NOT_FOUND')
            old, new = proof['old_worker_session_id'], proof['new_worker_session_id']
            pair = {'old': old, 'new': new}
            if old == new:
                raise ApiError(409, 'LEASE_CONFLICT')
            retry = task.get('recovery') == pair and task['worker_session_id'] == new
            if (task['worker_id'] != worker or task['lease_token'] != proof['lease_token'] or
                    (task['worker_session_id'] != old and not retry)):
                raise ApiError(409, 'LEASE_CONFLICT')
            guard = self.workers.document(worker).get(transaction=tx).to_dict() or {}
            if task['status'] not in ACTIVE:
                code = (task.get('error') or {}).get('code')
                raise ApiError(409, code if code in EXPIRY else 'TASK_ALREADY_TERMINAL')
            if (guard.get('task_id'), guard.get('worker_session_id')) != (task['task_id'], task['worker_session_id']):
                raise ApiError(409, 'LEASE_CONFLICT')
            expiry = self._expire(tx, task, guard)
            if expiry:
                return expiry
            changes = dict(worker_session_id=new, recovery=pair, updated_at=self.clock(),
                           lease_deadline=min(self.clock() + timedelta(seconds=self.s.lease_seconds), task['execution_deadline']))
            tx.update(ref, changes)
            tx.set(self.workers.document(worker), {'task_id': task['task_id'], 'worker_session_id': new})
            return {**task, **changes}
        return self.transaction(recover)

    def sweep(self, limit=100):
        candidates = set()
        for field in ('lease_deadline', 'execution_deadline'):
            q = self.tasks.where(filter=FieldFilter('status', 'in', list(ACTIVE))).where(
                filter=FieldFilter(field, '<=', self.clock())).order_by(field).limit(limit)
            candidates.update(s.id for s in q.stream())
        count = 0
        for task_id in candidates:
            def expire(tx):
                task = self.tasks.document(task_id).get(transaction=tx).to_dict()
                if not task or task['status'] not in ACTIVE:
                    return False
                guard = self.workers.document(task['worker_id']).get(transaction=tx).to_dict() or {}
                return bool(self._expire(tx, task, guard))
            count += self.transaction(expire)
        return count

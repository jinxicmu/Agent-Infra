import os
import pytest
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from cloudrun.config import Settings
from cloudrun.task_store import TaskStore


@pytest.fixture
def settings():
    return Settings(revision='test-revision', clients={'client-a': 'a' * 32, 'client-b': 'b' * 32},
                    workers={'worker-a': 'c' * 32, 'worker-b': 'd' * 32}, client_rpm=1000)


@pytest.fixture
def store(settings):
    if not os.getenv('FIRESTORE_EMULATOR_HOST'):
        pytest.skip('Run against the Firestore emulator; production Firestore is never used in tests')
    db = firestore.Client(project='demo-agent-infra', credentials=AnonymousCredentials())
    for collection in ('tasks', 'workers', 'idempotency', 'client_rates'):
        for doc in db.collection(collection).stream():
            doc.reference.delete()
    yield TaskStore(db, settings)
    db.close()


@pytest.fixture
def request_body():
    return {'model': 'MiniMax-H3', 'mode': 'realtime', 'resolution': '768P', 'duration': 5,
            'ratio': '16:9', 'content': [{'type': 'text', 'text': 'A smooth transition'},
            {'type': 'image_url', 'role': 'first_frame', 'image_url': 'https://example.com/a.png'},
            {'type': 'image_url', 'role': 'last_frame', 'image_url': 'https://example.com/b.png'}]}

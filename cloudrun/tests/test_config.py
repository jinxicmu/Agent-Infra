import json

import pytest

from cloudrun.config import Settings

BASE_ENV = {
    'CLIENT_API_KEYS_JSON': json.dumps({'client-a': 'a' * 32}),
    'WORKER_API_KEYS_JSON': json.dumps({'worker-a': 'b' * 32}),
    'SCHEDULER_SERVICE_ACCOUNT': 'scheduler@example.iam.gserviceaccount.com',
    'SCHEDULER_AUDIENCE': 'https://example.run.app',
}
LIMIT_VARS = ('REALTIME_QUEUE_LIMIT', 'BATCH_QUEUE_LIMIT', 'TOTAL_QUEUE_LIMIT', 'CLIENT_RPM')


@pytest.fixture
def env(monkeypatch):
    for name, value in BASE_ENV.items():
        monkeypatch.setenv(name, value)
    for name in LIMIT_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_admission_limits_default_to_previous_values(env):
    s = Settings.from_env()
    assert (s.realtime_limit, s.batch_limit, s.total_limit, s.client_rpm) == (20, 200, 220, 60)


def test_admission_limits_come_from_environment(env):
    env.setenv('REALTIME_QUEUE_LIMIT', '500')
    env.setenv('BATCH_QUEUE_LIMIT', '200')
    env.setenv('TOTAL_QUEUE_LIMIT', '700')
    env.setenv('CLIENT_RPM', '300')
    s = Settings.from_env()
    assert (s.realtime_limit, s.batch_limit, s.total_limit, s.client_rpm) == (500, 200, 700, 300)


@pytest.mark.parametrize('value', ['0', '-5', 'many', '1.5'])
def test_invalid_limit_is_rejected(env, value):
    env.setenv('REALTIME_QUEUE_LIMIT', value)
    with pytest.raises(ValueError, match='REALTIME_QUEUE_LIMIT'):
        Settings.from_env()


def test_total_limit_cannot_be_smaller_than_a_mode_limit(env):
    env.setenv('REALTIME_QUEUE_LIMIT', '500')
    with pytest.raises(ValueError, match='TOTAL_QUEUE_LIMIT'):
        Settings.from_env()

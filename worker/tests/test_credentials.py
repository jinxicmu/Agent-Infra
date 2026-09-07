from types import SimpleNamespace
from unittest.mock import Mock
from google.auth.exceptions import RefreshError
import pytest
from worker.credentials import GcloudImpersonatedCredentials


def test_gcloud_uses_explicit_identity_and_short_lived_token(monkeypatch):
    run = Mock(return_value=SimpleNamespace(stdout='token-value\n'))
    monkeypatch.setattr('worker.credentials.subprocess.run', run)
    credentials = GcloudImpersonatedCredentials('project', 'source@example.com', 'target@example.com')
    credentials.refresh(None)
    assert credentials.token == 'token-value'
    command = run.call_args.args[0]
    assert command[command.index('--account')+1] == 'source@example.com'
    assert command[command.index('--impersonate-service-account')+1] == 'target@example.com'
    assert credentials.valid


def test_gcloud_rejects_empty_token(monkeypatch):
    monkeypatch.setattr('worker.credentials.subprocess.run', lambda *a, **k: SimpleNamespace(stdout=''))
    with pytest.raises(RefreshError):
        GcloudImpersonatedCredentials('project','source','target').refresh(None)

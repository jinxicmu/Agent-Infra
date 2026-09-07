"""Keyless upload credentials using an explicitly selected local gcloud account."""
import subprocess
from datetime import datetime, timedelta
from google.auth.credentials import Credentials
from google.auth.exceptions import RefreshError


class GcloudImpersonatedCredentials(Credentials):
    def __init__(self, project, account, target):
        super().__init__()
        if not account or not target:
            raise ValueError('gcloud mode requires a source account and target service account')
        self.project, self.account, self.target = project, account, target

    def refresh(self, request):
        try:
            result = subprocess.run([
                'gcloud', 'auth', 'print-access-token', '--quiet',
                '--project', self.project, '--account', self.account,
                '--impersonate-service-account', self.target,
            ], capture_output=True, text=True, timeout=45, check=True)
        except (subprocess.SubprocessError, OSError) as exc:
            # gcloud stderr may contain account details; never include tokens or raw output.
            raise RefreshError('Unable to refresh gcloud impersonation; check the source account login') from None
        token = result.stdout.strip()
        if not token or any(c.isspace() for c in token):
            raise RefreshError('gcloud returned an invalid access token')
        self.token = token
        # Impersonated tokens default to one hour; refresh conservatively after 45 minutes.
        self.expiry = datetime.utcnow() + timedelta(minutes=45)

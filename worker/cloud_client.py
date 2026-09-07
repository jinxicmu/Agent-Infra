import threading
import requests


class CloudError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(f'{status} {code}')


class CloudClient:
    def __init__(self, settings):
        self.base = settings.cloud_url
        self._local = threading.local()
        self.api_key = settings.api_key
        self.revision = settings.manifest['revision']

    @property
    def session(self):
        if not hasattr(self._local, 'session'):
            self._local.session = requests.Session()
            self._local.session.headers['Authorization'] = 'Bearer ' + self.api_key
        return self._local.session

    def post(self, path, body):
        response = self.session.post(self.base + '/internal/' + path, json=body,
                                     timeout=(5, 15), allow_redirects=False)
        if response.status_code == 204:
            return None
        if response.status_code >= 300:
            try:
                code = response.json()['error']['code']
            except (ValueError, KeyError, TypeError):
                code = 'INVALID_CLOUD_RESPONSE'
            raise CloudError(response.status_code, code)
        return response.json()

    def claim(self, session):
        return self.post('workers/claim', {'worker_session_id': session, 'workflow_revision': self.revision})

    def recover(self, proof):
        return self.post('workers/recover', {**proof, 'workflow_revision': self.revision})

    def task(self, assignment, action, **fields):
        return self.post(f"tasks/{assignment['task_id']}/{action}", {
            'worker_session_id': assignment['worker_session_id'],
            'lease_token': assignment['lease_token'], 'workflow_revision': self.revision, **fields})

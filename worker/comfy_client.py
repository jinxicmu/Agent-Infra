import requests


class ComfyClient:
    def __init__(self, base):
        self.base = base
        self.session = requests.Session()
        self.session.trust_env = False

    def get(self, path):
        response = self.session.get(self.base + path, timeout=(3, 10))
        response.raise_for_status()
        return response.json()

    def post(self, path, body):
        response = self.session.post(self.base + path, json=body, timeout=(3, 20))
        response.raise_for_status()
        return response.json()

    def submit(self, graph, task_id):
        value = self.post('/prompt', {'prompt': graph, 'client_id': task_id,
                                     'extra_data': {'client_id': task_id}})
        if 'prompt_id' not in value:
            raise RuntimeError('ComfyUI rejected prompt')
        return value['prompt_id']

    def queue(self):
        data = self.get('/queue')
        return data.get('queue_running', []) + data.get('queue_pending', [])

    def history(self, prompt_id):
        return self.get('/history/' + prompt_id).get(prompt_id)

    def reconcile(self, task_id):
        # Queue tuples: number, prompt_id, graph, extra_data, output_nodes.
        for item in self.queue():
            if len(item) > 3 and item[3].get('client_id') == task_id:
                return item[1]
        for prompt_id, history in self.get('/history?max_items=100').items():
            item = history.get('prompt', [])
            if len(item) > 3 and item[3].get('client_id') == task_id:
                return prompt_id
        return None

    def interrupt(self):
        # Instance must be dedicated to this GPU worker; no other owner is allowed.
        self.post('/interrupt', {})
        self.post('/queue', {'clear': True})

import fcntl
import json
import os
from pathlib import Path


class Journal:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory/'active.json'
        self.lock_file = (self.directory/'worker.lock').open('a')
        fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def read(self):
        return json.loads(self.path.read_text()) if self.path.exists() else None

    def write(self, value):
        tmp = self.path.with_suffix('.tmp')
        with tmp.open('w') as stream:
            os.chmod(tmp, 0o600)
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, self.path)
        self._sync_dir()

    def clear(self):
        self.path.unlink(missing_ok=True)
        self._sync_dir()

    def _sync_dir(self):
        fd = os.open(self.directory, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

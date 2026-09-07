import logging
import signal
from worker.config import Settings
from worker.cloud_client import CloudClient
from worker.comfy_client import ComfyClient
from worker.gcs_uploader import Uploader
from worker.journal import Journal
from worker.runner import Runner


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    settings = Settings.from_env()
    runner = Runner(settings, CloudClient(settings), ComfyClient(settings.comfy_url),
                    Journal(settings.state_dir), Uploader(settings))
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: runner.shutdown.set())
    runner.run()


if __name__ == '__main__':
    main()

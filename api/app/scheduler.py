"""The background loop that runs due jobs and polls the channels, started with the API.

It is a thread in the API process, which keeps the free hosting to one service. Each tick takes
a short database transaction to claim work, so several API processes can run it side by side.
"""

import logging
import threading
import time
from collections.abc import Callable

from sqlmodel import Session

from app.channels import Channels
from app.sync import poll_channels, run_due_jobs

logger = logging.getLogger(__name__)


class SyncScheduler:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        channels: Channels,
        job_seconds: float,
        poll_seconds: float,
    ) -> None:
        self.session_factory = session_factory
        self.channels = channels
        self.job_seconds = job_seconds
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="sync-scheduler", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self.job_seconds + 15)

    def _loop(self) -> None:
        next_poll = time.monotonic()
        while not self._stop.is_set():
            try:
                if time.monotonic() >= next_poll:
                    next_poll = time.monotonic() + self.poll_seconds
                    poll_channels(self.session_factory, self.channels)
                run_due_jobs(self.session_factory, self.channels)
            except Exception:
                # The database may be briefly away, and the next tick tries again.
                logger.exception("Sync tick failed")
            self._stop.wait(self.job_seconds)

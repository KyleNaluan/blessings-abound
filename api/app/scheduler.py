"""The background loops that run due jobs, poll the channels and explain new flags, started
with the API.

They are threads in the API process, which keeps the free hosting to one service. Each tick takes
a short database transaction to claim work, so several API processes can run them side by side.
Explaining a flag waits on the model, so it has a thread of its own and never holds up a delist.
"""

import logging
import threading
import time
from collections.abc import Callable, Sequence

from sqlmodel import Session

from app.ai import ChatModel
from app.channels import Channels
from app.flag_explanations import explain_open_flags
from app.sync import poll_channels, run_due_jobs

logger = logging.getLogger(__name__)


class SyncScheduler:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        channels: Channels,
        job_seconds: float,
        poll_seconds: float,
        providers: Callable[[], Sequence[ChatModel]],
    ) -> None:
        self.session_factory = session_factory
        self.channels = channels
        self.job_seconds = job_seconds
        self.poll_seconds = poll_seconds
        self.providers = providers
        self._stop = threading.Event()
        self._threads = [
            threading.Thread(target=self._loop, name="sync-scheduler", daemon=True),
            threading.Thread(target=self._explain_loop, name="flag-explainer", daemon=True),
        ]

    def start(self) -> None:
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            # The explainer may be waiting on the model, and it is a daemon, so it isn't waited
            # for past this.
            thread.join(timeout=self.job_seconds + 15)

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

    def _explain_loop(self) -> None:
        while not self._stop.is_set():
            try:
                explain_open_flags(self.session_factory, self.providers())
            except Exception:
                logger.exception("Explaining flags failed")
            self._stop.wait(self.job_seconds)

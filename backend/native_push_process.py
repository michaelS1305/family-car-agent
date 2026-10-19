"""One spawned interpreter per pass: no inherited DB sockets or detached sends.

The hard deadline covers process startup, DB acquisition, OAuth, FCM and commit.
No work is replayed when termination leaves an ambiguous committed lease.
"""
import asyncio
from contextlib import contextmanager
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

PASS_SECONDS = 20.0
REAP_SECONDS = 1.0
log = logging.getLogger(__name__)


class Supervisor:
    def __init__(self, command=None, seconds=PASS_SECONDS):
        self.command = command or [sys.executable, '-B', '-m', 'native_push_process', '--run-pass']
        self.seconds = seconds
        self.child = None
        self.quarantined = False

    async def _wait_exit(self, seconds):
        end = time.monotonic() + seconds
        while self.child.poll() is None and time.monotonic() < end:
            await asyncio.sleep(.025)
        return self.child.poll() is not None

    async def close(self):
        if self.child is None:
            return True
        if self.quarantined and self.child.poll() is None:
            return False
        if self.child.poll() is None:
            try:
                self.child.terminate()
            except OSError:
                pass
            if not await self._wait_exit(REAP_SECONDS):
                try:
                    self.child.kill()
                except OSError:
                    pass
                if not await self._wait_exit(REAP_SECONDS):
                    # Fail closed: never spawn a replacement while a child may live.
                    self.quarantined = True
                    log.error('native_push_child_quarantined')
                    return False
        self.child = None  # poll() reaps the exited child; no unbounded wait().
        return True

    async def run(self, stop):
        if self.quarantined or self.child is not None or stop.is_set():
            return 'stopped'
        deadline = time.monotonic() + self.seconds
        try:
            self.child = subprocess.Popen(self.command, cwd=str(Path(__file__).resolve().parent),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            while self.child.poll() is None:
                if stop.is_set() or time.monotonic() >= deadline:
                    return 'uncertain'
                await asyncio.sleep(.025)
            code = self.child.returncode
            return 'complete' if code == 0 else ('uncertain' if code == 124 or code < 0 else 'failed')
        except OSError:
            return 'failed'
        finally:
            await self.close()


class ChildConnections:
    """Created only in the fresh child; no global application pool/import."""
    @contextmanager
    def connection(self):
        import psycopg
        with psycopg.connect(os.environ['DATABASE_URL'], connect_timeout=3,
                             options='-c statement_timeout=3000 -c lock_timeout=1000') as conn:
            yield conn


def child_pass():
    from native_push_outbox import enabled
    if not enabled():
        return 0
    from native_push_security import Config
    from native_push_fcm import Fcm
    from native_push_worker import run_once
    from native_push_cleanup import cleanup
    provider = None
    try:
        config = Config.load()
        provider = Fcm(config)
        pool = ChildConnections()
        run_once(pool, config, provider)
        cleanup(pool)
        return 0
    except Exception:
        # Never serialize child exception/connection/provider content to parent.
        return 1
    finally:
        if provider is not None:
            provider.close()


if __name__ == '__main__':
    # Also bound an orphan if the supervising web process dies abruptly.
    watchdog = threading.Timer(PASS_SECONDS, lambda: os._exit(124))
    watchdog.daemon = True
    watchdog.start()
    raise SystemExit(child_pass() if sys.argv[1:] == ['--run-pass'] else 2)

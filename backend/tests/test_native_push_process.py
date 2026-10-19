"""Real local child-process supervision; never loads provider credentials/DB."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from native_push_process import Supervisor, child_pass
from native_push_cleanup import batch_size


class ProcessTests(unittest.TestCase):
    def run_async(self, function):
        return asyncio.run(function())

    def test_success_and_fast_failure(self):
        async def check():
            for code, expected in [(0,'complete'),(1,'failed')]:
                supervisor=Supervisor([sys.executable,'-B','-c',f'raise SystemExit({code})'],seconds=3)
                self.assertEqual(await supervisor.run(asyncio.Event()),expected)
                self.assertIsNone(supervisor.child)
        self.run_async(check)

    def test_stalled_oauth_or_fcm_is_killed_and_reaped(self):
        async def check():
            for stage in ('oauth','fcm'):
                with self.subTest(stage=stage):
                    code = ("import time; from datetime import datetime,timedelta,timezone; "
                            "from unittest.mock import Mock; from native_push_fcm import Fcm; "
                            "p=Fcm(Mock(project='test-only'),transport=Mock()); ")
                    code += ("p._access_token=lambda: time.sleep(60); " if stage=='oauth' else
                             "p._token='mock'; p._until=float('inf'); p.http.post.side_effect=lambda *a,**k: time.sleep(60); ")
                    code += "p.send('mock',{'kind':'refresh','version':'1'},expires_at=datetime.now(timezone.utc)+timedelta(minutes=1),platform='android')"
                    supervisor=Supervisor([sys.executable,'-B','-c',code],seconds=2)
                    start=time.monotonic()
                    self.assertEqual(await supervisor.run(asyncio.Event()),'uncertain')
                    self.assertLess(time.monotonic()-start,5)
                    self.assertIsNone(supervisor.child)
                    self.assertFalse(supervisor.quarantined)
        self.run_async(check)

    def test_shutdown_interrupts_stalled_child(self):
        async def check():
            stop=asyncio.Event()
            supervisor=Supervisor([sys.executable,'-B','-c','import time; time.sleep(60)'])
            task=asyncio.create_task(supervisor.run(stop))
            await asyncio.sleep(.1)
            stop.set()
            self.assertEqual(await asyncio.wait_for(task,3),'uncertain')
            self.assertIsNone(supervisor.child)
        self.run_async(check)

    def test_no_parallel_replacement(self):
        async def check():
            stop=asyncio.Event()
            supervisor=Supervisor([sys.executable,'-B','-c','import time; time.sleep(60)'])
            task=asyncio.create_task(supervisor.run(stop))
            await asyncio.sleep(.1)
            self.assertEqual(await supervisor.run(stop),'stopped')
            stop.set()
            await task
        self.run_async(check)

    def test_timeout_leaves_no_delayed_child_side_effect(self):
        async def check():
            with tempfile.TemporaryDirectory(prefix='fca-process-test-') as directory:
                marker=Path(directory)/'must-not-exist'
                code=f"import time,pathlib; time.sleep(1); pathlib.Path({str(marker)!r}).touch()"
                supervisor=Supervisor([sys.executable,'-B','-c',code],seconds=.3)
                self.assertEqual(await supervisor.run(asyncio.Event()),'uncertain')
                await asyncio.sleep(1.2)
                self.assertFalse(marker.exists(), 'A descendant survived timeout')
        self.run_async(check)

    def test_quarantine_prohibits_restart(self):
        async def check():
            supervisor=Supervisor()
            supervisor.quarantined=True
            self.assertEqual(await supervisor.run(asyncio.Event()),'stopped')
        self.run_async(check)

    def test_disabled_child_does_not_read_credentials(self):
        with patch.dict(os.environ,{'NATIVE_PUSH_ENABLED':'false'}),patch('native_push_security.Config.load') as load:
            self.assertEqual(child_pass(),0)
        load.assert_not_called()

    def test_invalid_config_child_fails_sanitized(self):
        with patch.dict(os.environ,{'NATIVE_PUSH_ENABLED':'true'},clear=True):
            self.assertEqual(child_pass(),1)

    def test_cleanup_batch_bounds(self):
        for value,expected in [('0',1),('10000',100),('bad',50),('5',5)]:
            with patch.dict(os.environ,{'NATIVE_PUSH_CLEANUP_BATCH':value}):
                self.assertEqual(batch_size(),expected)

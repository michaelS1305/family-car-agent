"""No network/Gradle/sleeps: download, integrity and version compatibility regressions."""
import contextlib
import hashlib
import io
from pathlib import Path
import ssl
import tempfile
import unittest
import urllib.error
from unittest.mock import Mock
import prepare_robolectric_runtime as runtime

class Response(io.BytesIO):
    status = 200
    def __init__(self, data=b'valid jar', length=None):
        super().__init__(data)
        self.headers = {'Content-Length': str(len(data) if length is None else length)}

class RuntimeChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.artifact = dict(runtime.load_manifest()['artifacts'][0], sha512=hashlib.sha512(b'valid jar').hexdigest())
        self.sleep = Mock()
        self.logs = io.StringIO()
        self.capture = contextlib.redirect_stdout(self.logs); self.capture.__enter__(); self.addCleanup(self.capture.__exit__, None, None, None)

    def prepare(self, opener):
        return runtime.prepare(self.artifact, self.directory, opener, self.sleep)

    def error(self, code):
        return urllib.error.HTTPError(runtime.source(self.artifact),code,'DO_NOT_LOG',{},None)

    def test_success_and_verified_reuse(self):
        opener=Mock(return_value=Response()); path=self.prepare(opener)
        self.assertEqual(path.read_bytes(), b'valid jar')
        self.prepare(opener); self.assertEqual(opener.call_count,1)
        self.assertFalse(list(self.directory.glob('*.partial')))
        self.assertIn('verified_existing',self.logs.getvalue())

    def test_checksum_mismatch_fails_closed(self):
        opener=Mock(return_value=Response(b'corrupt'))
        with self.assertRaisesRegex(runtime.PreparationError,'checksum_mismatch'): self.prepare(opener)
        self.assertEqual(list(self.directory.iterdir()),[]); self.sleep.assert_not_called()

    def test_partial_download(self):
        with self.assertRaisesRegex(runtime.PreparationError,'partial_download'):
            self.prepare(Mock(return_value=Response(length=999)))
        self.assertEqual(list(self.directory.iterdir()),[]); self.sleep.assert_not_called()

    def test_modified_existing_never_used(self):
        (self.directory/runtime.filename(self.artifact)).write_bytes(b'changed')
        opener=Mock()
        with self.assertRaisesRegex(runtime.PreparationError,'existing_integrity_failed'): self.prepare(opener)
        opener.assert_not_called(); self.sleep.assert_not_called()

    def test_transient_then_success(self):
        for code in (429,502,503,504):
            with self.subTest(code=code):
                opener=Mock(side_effect=[self.error(code),Response()])
                path=self.prepare(opener); path.unlink()
                self.assertEqual(opener.call_count,2)
                self.sleep.assert_called_with(60)
                self.assertIn(f'http_status={code}',self.logs.getvalue())

    def test_retry_exhaustion(self):
        opener=Mock(side_effect=self.error(429))
        with self.assertRaises(runtime.PreparationError): self.prepare(opener)
        self.assertEqual(opener.call_count,3)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list],[60,120])
        self.assertEqual(list(self.directory.iterdir()),[])

    def test_permanent_http_no_retry(self):
        for code in (301,400,401,403,404,500):
            opener=Mock(side_effect=self.error(code))
            with self.assertRaises(runtime.PreparationError): self.prepare(opener)
            self.assertEqual(opener.call_count,1)
        self.sleep.assert_not_called()
        self.assertNotIn('DO_NOT_LOG',self.logs.getvalue())

    def test_tls_transport_and_unclassified_no_retry(self):
        for error in (ssl.SSLError('PRIVATE'),urllib.error.URLError(ssl.SSLError('PRIVATE')),
                      urllib.error.URLError('PRIVATE'),RuntimeError('PRIVATE')):
            opener=Mock(side_effect=error)
            with self.assertRaises(runtime.PreparationError): self.prepare(opener)
            self.assertEqual(opener.call_count,1)
        self.sleep.assert_not_called(); self.assertNotIn('PRIVATE',self.logs.getvalue())

    def test_interrupted_read_cleanup(self):
        response=Response(); response.read=Mock(side_effect=runtime.http.client.IncompleteRead(b'part',99))
        with self.assertRaisesRegex(runtime.PreparationError,'partial_download'): self.prepare(Mock(return_value=response))
        self.assertEqual(list(self.directory.iterdir()),[]); self.sleep.assert_not_called()

    def test_no_redirect(self):
        self.assertIsNone(runtime.NoRedirect().redirect_request(None,None,302,'',{},'https://untrusted.invalid'))

    def test_artifact_version_and_sdk_compatibility(self):
        root=Path(__file__).resolve().parents[1]
        manifest=runtime.load_manifest()
        self.assertIn('org.robolectric:robolectric:'+manifest['robolectric_version'],(root/'android/app/build.gradle.kts').read_text())
        self.assertEqual([(a['sdk'],a['version']) for a in manifest['artifacts']],
                         [(35,'15-robolectric-13954326-i7'),(36,'16-robolectric-13921718-i7')])
        import re
        sdks=set()
        for path in (root/'android/app/src/test').rglob('*.kt'):
            for match in re.findall(r'@Config\(sdk\s*=\s*\[([^]]+)\]',path.read_text(encoding='utf-8')):
                sdks.update(int(x.strip()) for x in match.split(','))
        self.assertEqual(sdks,{a['sdk'] for a in manifest['artifacts']})
        self.assertIn('targetSdk = 36',(root/'android/app/build.gradle.kts').read_text())
        for a in manifest['artifacts']:
            self.assertTrue(runtime.source(a).startswith('https://repo.maven.apache.org/maven2/'))

    def test_gradle_init_requires_verified_files_and_sets_test_jvm(self):
        source=Path(__file__).with_name('robolectric-offline.init.gradle').read_text()
        for required in ('withType(Test).configureEach',"task.systemProperty('robolectric.dependency.dir'",
                         "task.systemProperty('robolectric.offline', 'true')",'network fallback disabled',
                         "MessageDigest.getInstance('SHA-512')",'artifact.sha512'):
            self.assertIn(required,source)

if __name__=='__main__': unittest.main()

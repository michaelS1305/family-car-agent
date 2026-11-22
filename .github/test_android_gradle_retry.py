"""Offline checks; no Gradle invocation or real sleeps."""
import importlib.util
import contextlib
import io
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import yaml

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('retry', ROOT / 'android_gradle_retry.py')
retry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retry)
URL = 'https://repo.maven.apache.org/maven2/org/robolectric/nativeruntime-dist-compat/1.0.18/nativeruntime-dist-compat-1.0.18.jar'
ERROR = f"""FAILURE: Build failed with an exception.
* What went wrong:
Execution failed for task ':app:generateProdDebugUnitTestLintModel'.
> Could not resolve all files for configuration ':app:prodDebugUnitTestRuntimeClasspath'.
   > Could not download nativeruntime-dist-compat-1.0.18.jar (org.robolectric:nativeruntime-dist-compat:1.0.18)
      > Could not get resource '{URL}'.
         > Could not GET '{URL}'. Received status code 429 from server: Too Many Requests
* Try:
Run with --stacktrace option.
"""


# Verbatim failure explanations from CI run 45039872929; timestamp prefixes removed.
CI_FIRST = "* What went wrong:\nExecution failed for task ':app:generateProdDebugUnitTestLintModel'.\n> Could not resolve all files for configuration ':app:prodDebugUnitTestRuntimeClasspath'.\n   > Could not download nativeruntime-dist-compat-1.0.18.jar (org.robolectric:nativeruntime-dist-compat:1.0.18)\n      > Could not get resource 'https://repo.maven.apache.org/maven2/org/robolectric/nativeruntime-dist-compat/1.0.18/nativeruntime-dist-compat-1.0.18.jar'.\n         > Could not GET 'https://repo.maven.apache.org/maven2/org/robolectric/nativeruntime-dist-compat/1.0.18/nativeruntime-dist-compat-1.0.18.jar'. Received status code 429 from server: Too Many Requests\n\n* Try:\n"
CI_SECOND = "* What went wrong:\nExecution failed for task ':app:testProdDebugUnitTest'.\n> Could not resolve all files for configuration ':app:prodDebugUnitTestRuntimeClasspath'.\n   > Failed to transform nativeruntime-dist-compat-1.0.18.jar (org.robolectric:nativeruntime-dist-compat:1.0.18) to match attributes ***artifactType=android-classes-jar, org.gradle.category=library, org.gradle.libraryelements=jar, org.gradle.status=release, org.gradle.usage=java-runtime***.\n      > Could not download nativeruntime-dist-compat-1.0.18.jar (org.robolectric:nativeruntime-dist-compat:1.0.18)\n         > Could not get resource 'https://repo.maven.apache.org/maven2/org/robolectric/nativeruntime-dist-compat/1.0.18/nativeruntime-dist-compat-1.0.18.jar'.\n            > Could not GET 'https://repo.maven.apache.org/maven2/org/robolectric/nativeruntime-dist-compat/1.0.18/nativeruntime-dist-compat-1.0.18.jar'. Received status code 429 from server: Too Many Requests\n\n* Try:\n"

class RetryChecks(unittest.TestCase):
    def test_actual_ci_failure_reaches_third_attempt(self):
        self.assertTrue(retry.eligible(CI_FIRST))
        self.assertTrue(retry.eligible(CI_SECOND))
        # GitHub masks brace values in this log; Gradle's original form uses braces.
        self.assertTrue(retry.eligible(CI_SECOND.replace('***artifactType', '{artifactType').replace('java-runtime***', 'java-runtime}')))
        for final_status, final_output in [(0, 'BUILD SUCCESSFUL'), (7, CI_SECOND)]:
            run = Mock(side_effect=[(1, CI_FIRST), (1, CI_SECOND), (final_status, final_output)])
            sleep = Mock()
            self.assertEqual(retry.validate(['task'], run, sleep), final_status)
            self.assertEqual(run.call_count, 3)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [60, 120])

    def test_transform_rejects_non_429_and_unrelated_failures(self):
        wrapper = next(line for line in CI_SECOND.splitlines() if 'Failed to transform' in line)
        for cause in ['Execution failed for JetifyTransform: corrupt jar.', 'Compilation error.',
                      'Lint found errors in the project.', 'There were failing tests.']:
            bad = '* What went wrong:\n' + wrapper + '\n      > ' + cause + '\n* Try:\n'
            for output in [bad, bad + CI_FIRST, CI_SECOND.replace('* Try:', '      > ' + cause + '\n* Try:')]:
                run = Mock(return_value=(1, output)); sleep = Mock()
                self.assertEqual(retry.validate(['task'], run, sleep), 1)
                run.assert_called_once(); sleep.assert_not_called()
        # A same-level 429 is not the transform's underlying cause.
        sibling = CI_SECOND.replace('      >', '   >').replace('         >', '   >').replace('            >', '   >')
        self.assertFalse(retry.eligible(sibling))
        self.assertFalse(retry.eligible(CI_SECOND.replace('429', '404')))
        self.assertFalse(retry.eligible(CI_SECOND.replace('repo.maven.apache.org', 'untrusted.example')))
        self.assertFalse(retry.eligible('* What went wrong:\n' + wrapper + '\n' + CI_FIRST.split('* What went wrong:\n')[1]))

    def test_only_central_resolution_429(self):
        self.assertTrue(retry.eligible(ERROR))
        self.assertTrue(retry.eligible(ERROR.replace('repo.maven.apache.org', 'repo1.maven.org')))
        for bad in [ERROR.replace('429', '503'), ERROR.replace('repo.maven.apache.org', 'evil.example'),
                    ERROR.replace('repo.maven.apache.org', 'repo.maven.apache.org.evil.example'),
                    ERROR + '\n* What went wrong:\nExecution failed for task test.\n> There were failing tests.\n* Try:\n',
                    ERROR.replace('* Try:', '> Compilation error.\n* Try:'),
                    ERROR.replace('* Try:', '> Lint found errors in the project.\n* Try:'),
                    ERROR.replace('* What went wrong:', 'Warning:'),
                    '* What went wrong:\n> There were failing tests.\n* Try:\n' + ERROR.split('* Try:')[0].replace('* What went wrong:', 'Warning:')]:
            with self.subTest(output=bad):
                self.assertFalse(retry.eligible(bad))

    def test_three_attempts_and_final_exit_code(self):
        run = Mock(side_effect=[(1, ERROR), (2, ERROR), (7, ERROR)])
        sleep = Mock()
        self.assertEqual(retry.validate(['task'], run, sleep), 7)
        self.assertEqual(run.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [60, 120])

    def test_retry_then_success(self):
        run = Mock(side_effect=[(1, ERROR), (0, 'BUILD SUCCESSFUL')]); sleep = Mock()
        self.assertEqual(retry.validate(['task'], run, sleep), 0)
        self.assertEqual(run.call_count, 2); sleep.assert_called_once_with(60)

    def test_ordinary_failure_or_success_never_retried(self):
        for status, output in [(1, 'Compilation error'), (2, 'Lint found errors'), (3, 'There were failing tests'), (0, ERROR), (-15, ERROR)]:
            run = Mock(return_value=(status, output)); sleep = Mock()
            self.assertEqual(retry.validate(['task'], run, sleep), status if status >= 0 else 143)
            run.assert_called_once(); sleep.assert_not_called()

    def test_output_and_exit_status_preserved(self):
        process = Mock()
        process.stdout = iter(['useful Gradle output\n', ERROR])
        process.wait.return_value = 7
        manager = Mock()
        manager.__enter__ = Mock(return_value=process)
        manager.__exit__ = Mock(return_value=False)
        output = io.StringIO()
        with patch.object(retry.subprocess, 'Popen', return_value=manager) as launch, contextlib.redirect_stdout(output):
            status, captured = retry.run_once([':app:lintProdDebug'])
        self.assertEqual(status, 7)
        self.assertEqual(output.getvalue(), captured)
        self.assertIn(ERROR, captured)
        self.assertEqual(launch.call_args.args[0], ['bash', './gradlew', '--console=plain', ':app:lintProdDebug'])

    def test_workflow_cache_and_commands(self):
        workflow = yaml.safe_load((ROOT / 'workflows/android.yml').read_text())
        steps = workflow['jobs']['android']['steps']
        java = next(step for step in steps if step.get('uses') == 'actions/setup-java@v5')
        self.assertEqual(java['with']['cache'], 'gradle')
        self.assertEqual(java['with']['cache-dependency-path'].splitlines(), [
            'android/**/*.gradle.kts', 'android/gradle.properties', 'android/gradle/gradle-daemon-jvm.properties', 'android/gradle/wrapper/gradle-wrapper.properties'])
        for flavor in ('Dev', 'Prod'):
            step = next(step for step in steps if step.get('name') == f'{flavor} unit tests, lint and debug assembly')
            self.assertEqual(step['run'], f'python3 ../.github/android_gradle_retry.py :app:test{flavor}DebugUnitTest :app:lint{flavor}Debug :app:assemble{flavor}Debug')


if __name__ == '__main__':
    unittest.main()

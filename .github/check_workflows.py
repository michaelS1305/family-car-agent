"""Local static CI checks. Requires PyYAML; does not contact GitHub or run builds."""
import ast
import os
from pathlib import Path
import re
import subprocess
import unittest

import yaml


ROOT = Path(__file__).resolve().parent


def evaluate(expression, context):
    """Evaluate the limited boolean expressions used by signing job conditions."""
    def value(match):
        result = context
        for key in match.group().split('.'):
            result = result.get(key, False) if isinstance(result, dict) else False
        return repr(result)
    expression = re.sub(r'\b(?:github|inputs|vars)\.[\w.]+', value, expression)
    expression = expression.replace('&&', ' and ').replace('||', ' or ')
    expression = re.sub(r'!(?!=)', 'not ', expression)
    expression = re.sub(r"(?<!['\w])true(?!['\w])", 'True', expression)
    expression = re.sub(r"(?<!['\w])false(?!['\w])", 'False', expression)
    return bool(eval(expression, {'__builtins__': {}}, {}))


class WorkflowChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflows = {name: yaml.load((ROOT / 'workflows' / (name + '.yml')).read_text(), Loader=yaml.BaseLoader)
                         for name in ('android', 'ios', 'backend', 'web')}

    def test_events_and_revision_binding(self):
        for name, workflow in self.workflows.items():
            with self.subTest(workflow=name):
                self.assertEqual(set(workflow['on']), {'push', 'pull_request', 'workflow_dispatch'})
                self.assertEqual(workflow['on']['push']['branches'], ['develop'])
                self.assertEqual(workflow['on']['pull_request']['branches'], ['main'])
                self.assertNotIn('paths', workflow['on']['pull_request'])
                self.assertNotIn('closed', workflow['on']['pull_request']['types'])
                self.assertEqual(workflow['permissions'], {'contents': 'read'})
                self.assertEqual(workflow['concurrency']['cancel-in-progress'], 'true')
                self.assertIn('github.event.pull_request.number || github.ref', workflow['concurrency']['group'])
                for job in workflow['jobs'].values():
                    for step in job['steps']:
                        if step.get('uses', '').startswith('actions/checkout@'):
                            self.assertEqual(step['with']['ref'], '${{ github.sha }}')
                            self.assertEqual(step['with']['persist-credentials'], 'false')
                        if step.get('uses', '').startswith('actions/upload-artifact@'):
                            self.assertIn('github.sha', step['with']['name'])
                            self.assertEqual(step['with']['retention-days'], '7')

    def test_signing_event_matrix(self):
        for name, job, flag in [('android', 'production-release', 'production_release'),
                                ('ios', 'signed_production_ipa', 'build_production_ipa')]:
            expression = self.workflows[name]['jobs'][job]['if']
            for event, branch, source, head, base, enabled, draft, manual, expected in [
                ('push', 'develop', 'repo', 'develop', 'main', True, False, False, False),
                ('push', 'main', 'repo', 'develop', 'main', True, False, False, False),
                ('pull_request', 'pull/1/merge', 'repo', 'develop', 'main', True, False, False, True),
                ('pull_request', 'pull/1/merge', 'fork', 'develop', 'main', True, False, False, False),
                ('pull_request', 'pull/1/merge', 'repo', 'feature', 'main', True, False, False, False),
                ('pull_request', 'pull/1/merge', 'repo', 'develop', 'develop', True, False, False, False),
                ('pull_request', 'pull/1/merge', 'repo', 'develop', 'main', False, False, False, False),
                ('pull_request', 'pull/1/merge', 'repo', 'develop', 'main', True, True, False, False),
                ('workflow_dispatch', 'develop', 'repo', 'develop', 'main', True, False, True, True),
                ('workflow_dispatch', 'main', 'repo', 'develop', 'main', True, False, True, False),
                ('workflow_dispatch', 'develop', 'repo', 'develop', 'main', True, False, False, False),
            ]:
                context = {'github': {'event_name': event, 'ref': 'refs/heads/' + branch,
                                     'repository': 'repo', 'base_ref': base,
                                     'event': {'pull_request': {'draft': draft, 'head': {'repo': {'full_name': source}, 'ref': head}}}},
                           'vars': {'FCA_PROD_SIGN_ENABLED': 'true' if enabled else ''}, 'inputs': {flag: manual}}
                with self.subTest(workflow=name, event=event, head=head, enabled=enabled, source=source, draft=draft):
                    self.assertEqual(evaluate(expression, context), expected)

    def test_dependency_and_secret_boundaries(self):
        for name, validation, signing, environment in [
            ('android', 'android', 'production-release', 'android-production'),
            ('ios', 'ios', 'signed_production_ipa', 'ios-production-signing'),
        ]:
            jobs = self.workflows[name]['jobs']
            self.assertEqual(jobs[signing]['needs'], validation)
            self.assertEqual(jobs[signing]['environment'], environment)
            gate = jobs['required']
            self.assertEqual(gate['if'], 'always()')
            self.assertIn(validation, gate['needs'])
            self.assertIn(signing, gate['needs'])
            self.assertIn('skipped signing is not approval', gate['steps'][0]['run'])
            for step in jobs[validation]['steps']:
                for value in step.get('env', {}).values():
                    self.assertNotIn('secrets.FCA_IOS_PROD', value)
                    self.assertNotIn('secrets.FIREBASE_PROD', value)
                    self.assertNotIn('secrets.FCA_ANDROID_KEY', value)
                    self.assertNotIn('secrets.FCA_ANDROID_UPLOAD', value)

    def test_embedded_scripts_syntax(self):
        for workflow in self.workflows.values():
            for job in workflow['jobs'].values():
                for step in job['steps']:
                    if 'run' not in step:
                        continue
                    script = step['run']
                    subprocess.run(['bash', '-n'], input=script, text=True, check=True, capture_output=True)
                    for source in re.findall(r"python3 - <<'PY'\n(.*?)\nPY", script, re.S):
                        ast.parse(source)

    def test_required_gates_fail_on_skipped_failed_or_cancelled_signing(self):
        for name, validation, signing in [('android', 'VALIDATION', 'SIGNING'),
                                          ('ios', 'VALIDATION', 'PRODUCTION_SIGNING')]:
            script = self.workflows[name]['jobs']['required']['steps'][0]['run']
            for result in ('success', 'skipped', 'failure', 'cancelled'):
                env = dict(os.environ, PRODUCTION='true', **{validation: 'success', signing: result})
                code = subprocess.run(['bash', '-c', script], env=env, capture_output=True).returncode
                self.assertEqual(code == 0, result == 'success')
            env = dict(os.environ, PRODUCTION='true', **{validation: 'failure', signing: 'success'})
            self.assertNotEqual(subprocess.run(['bash', '-c', script], env=env, capture_output=True).returncode, 0)

    def test_dev_signing_is_automatic_but_never_on_pr(self):
        expression = self.workflows['ios']['jobs']['signed_dev_ipa']['if']
        for event, ref, enabled, requested, production, expected in [
            ('push', 'refs/heads/develop', True, False, False, True),
            ('push', 'refs/heads/develop', False, False, False, False),
            ('pull_request', 'refs/pull/1/merge', True, True, False, False),
            ('push', 'refs/heads/main', True, False, False, False),
            ('workflow_dispatch', 'refs/heads/develop', True, True, False, True),
            ('workflow_dispatch', 'refs/heads/develop', True, True, True, False),
        ]:
            context = {'github': {'ref': ref, 'event_name': event},
                       'vars': {'FCA_DEV_SIGN_ENABLED': 'true' if enabled else ''},
                       'inputs': {'build_signed_ipa': requested, 'build_production_ipa': production}}
            self.assertEqual(evaluate(expression, context), expected)


if __name__ == '__main__':
    unittest.main()

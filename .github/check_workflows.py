"""Local static CI checks. Requires PyYAML; does not contact GitHub or run builds."""
import ast
import os
from pathlib import Path
import re
import subprocess
import unittest

import yaml
from component_scope import classify


ROOT = Path(__file__).resolve().parent


def evaluate(expression, context):
    """Evaluate the limited boolean expressions used by signing job conditions."""
    def value(match):
        result = context
        for key in match.group().split('.'):
            result = result.get(key, False) if isinstance(result, dict) else False
        return repr(result)
    expression = re.sub(r'\b(?:github|inputs|vars|needs)\.[\w.]+', value, expression)
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
                self.assertEqual(workflow['on']['push']['branches'], ['develop', 'main'])
                self.assertEqual(workflow['on']['pull_request']['branches'], ['develop', 'main'])
                self.assertNotIn('paths', workflow['on']['pull_request'])
                self.assertNotIn('closed', workflow['on']['pull_request']['types'])
                self.assertEqual(workflow['permissions'], {'contents': 'read'})
                self.assertEqual(workflow['concurrency']['cancel-in-progress'], "${{ github.ref != 'refs/heads/main' }}" if name == 'ios' else 'true')
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
                                     'repository': 'michaelS1305/family-car-agent', 'base_ref': base,
                                     'event': {'pull_request': {'draft': draft, 'head': {'repo': {'full_name': 'michaelS1305/family-car-agent' if source == 'repo' else source}, 'ref': head}}}},
                           'needs': {'scope': {'outputs': {'android_release': 'true', 'ios_release': 'true'}}},
                           'vars': {'FCA_PROD_SIGN_ENABLED': 'true' if enabled else ''}, 'inputs': {flag: manual}}
                with self.subTest(workflow=name, event=event, head=head, enabled=enabled, source=source, draft=draft):
                    self.assertEqual(evaluate(expression, context), expected or (event == 'push' and branch == 'main' and enabled))

    def test_testflight_only_uploads_successful_main_artifact(self):
        jobs = self.workflows['ios']['jobs']
        upload = jobs['testflight']
        self.assertEqual(upload['needs'], ['ios', 'signed_production_ipa', 'required'])
        self.assertEqual(upload['environment'], 'ios-testflight-upload')
        for event, branch in [('push', 'main'), ('push', 'develop'), ('pull_request', 'main'), ('workflow_dispatch', 'main')]:
            for result in ('success', 'skipped', 'failure', 'cancelled'):
                for dependency in upload['needs']:
                    context = {'github': {'event_name': event, 'ref': 'refs/heads/' + branch,
                                          'repository': 'michaelS1305/family-car-agent'},
                               'vars': {'FCA_TESTFLIGHT_UPLOAD_ENABLED': 'true'},
                               'needs': {name: {'result': result if name == dependency else 'success'} for name in upload['needs']}}
                    self.assertEqual(evaluate(upload['if'], context), event == 'push' and branch == 'main' and result == 'success')
                    context['vars']['FCA_TESTFLIGHT_UPLOAD_ENABLED'] = ''
                    self.assertFalse(evaluate(upload['if'], context))
        download = next(s for s in upload['steps'] if s.get('uses') == 'actions/download-artifact@v4')
        self.assertEqual(download['with']['artifact-ids'], '${{ needs.signed_production_ipa.outputs.artifact_id }}')
        self.assertNotIn('run-id', download['with'])
        self.assertNotIn('xcodebuild', str(upload))
        self.assertNotIn('sign-fca-dev.py', str(upload))
        self.assertIn('GITHUB_RUN_ATTEMPT', str(upload))

    def test_dependency_and_secret_boundaries(self):
        for name, validation, signing, environment in [
            ('android', 'android', 'production-release', 'android-production'),
            ('ios', 'ios', 'signed_production_ipa', 'ios-production-signing'),
        ]:
            jobs = self.workflows[name]['jobs']
            self.assertEqual(jobs[signing]['needs'], ['scope', validation])
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

    def test_simulator_preserves_package_conditions_for_both_environments(self):
        step = next(step for step in self.workflows['ios']['jobs']['ios']['steps']
                    if step.get('name') == 'Compile iOS Simulator package without signing')
        # Capture actual shell arguments without Xcode, builds, or signing.
        script = "xcodebuild() { printf '%s\\n' \"$@\"; }\n" + step['run']
        for production, configuration, flag in [('false', 'Debug', 'DEBUG'),
                                                ('true', 'Release', 'FCA_PRODUCTION')]:
            result = subprocess.run(
                ['bash', '-eu', '-c', script], text=True, capture_output=True, check=True,
                env=dict(os.environ, PRODUCTION=production, RUNNER_TEMP='/tmp/fca-ci-check'),
            )
            args = result.stdout.splitlines()
            self.assertEqual(args[args.index('-configuration') + 1], configuration)
            # Xcode must expand inherited settings, NOT the shell. Without this,
            # Firebase loses SWIFT_PACKAGE and selects its non-SPM imports.
            self.assertIn('SWIFT_ACTIVE_COMPILATION_CONDITIONS=$(inherited) ' + flag, args)
            self.assertEqual(result.stderr, '')
            self.assertIn('CODE_SIGNING_ALLOWED=NO', args)
            self.assertIn('CODE_SIGNING_REQUIRED=NO', args)

    def test_required_gates_fail_on_skipped_failed_or_cancelled_signing(self):
        for name, validation, signing in [('android', 'VALIDATION', 'SIGNING'),
                                          ('ios', 'VALIDATION', 'PRODUCTION_SIGNING')]:
            script = self.workflows[name]['jobs']['required']['steps'][0]['run']
            for result in ('success', 'skipped', 'failure', 'cancelled'):
                env = dict(os.environ, PRODUCTION='true', SCOPE_RESULT='success', VALIDATE='true', RELEASE='true', DEVELOPMENT_SIGNING='skipped', **{validation: 'success', signing: result})
                code = subprocess.run(['bash', '-c', script], env=env, capture_output=True).returncode
                self.assertEqual(code == 0, result == 'success')
            env = dict(os.environ, PRODUCTION='true', SCOPE_RESULT='success', VALIDATE='true', RELEASE='true', DEVELOPMENT_SIGNING='skipped', **{validation: 'failure', signing: 'success'})
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
            context = {'needs': {'scope': {'outputs': {'ios_release': 'true'}}},
                       'github': {'ref': ref, 'event_name': event},
                       'vars': {'FCA_DEV_SIGN_ENABLED': 'true' if enabled else ''},
                       'inputs': {'build_signed_ipa': requested, 'build_production_ipa': production}}
            self.assertEqual(evaluate(expression, context), expected)

    def test_scope_job_complete_diff_and_policy_checks(self):
        for name, workflow in self.workflows.items():
            self.assertNotIn('paths', workflow['on']['push'])
            scope = workflow['jobs']['scope']
            self.assertEqual(scope['steps'][0]['with']['fetch-depth'], '0')
            self.assertIn('python3 .github/component_scope.py', str(scope))
            self.assertIn('python3 .github/test_component_scope.py', str(scope))
            self.assertIn('python3 .github/check_workflows.py', str(scope))
            self.assertIn(name + '_validation', scope['outputs'])
            self.assertIn(name + '_release', scope['outputs'])

    def test_required_scope_states(self):
        for name in ('android', 'ios', 'backend', 'web'):
            job = self.workflows[name]['jobs']['required' if name in ('android', 'ios') else name]
            script = job['steps'][0]['run']
            for scope, validate, validation, release, signing, expected in [
                ('success', 'false', 'skipped', 'false', 'skipped', True),
                ('success', 'true', 'success', 'false', 'skipped', True),
                ('success', 'true', 'failure', 'false', 'skipped', False),
                ('success', 'true', 'cancelled', 'false', 'skipped', False),
                ('success', 'true', 'skipped', 'false', 'skipped', False),
                ('failure', 'false', 'skipped', 'false', 'skipped', False),
                ('cancelled', 'false', 'skipped', 'false', 'skipped', False),
                ('success', '', 'skipped', 'false', 'skipped', False),
                ('success', 'false', 'failure', 'false', 'skipped', False),
            ]:
                env = dict(os.environ, SCOPE_RESULT=scope, VALIDATE=validate, VALIDATION=validation,
                           RELEASE=release, PRODUCTION='true', SIGNING=signing, PRODUCTION_SIGNING=signing, DEVELOPMENT_SIGNING='skipped')
                self.assertEqual(subprocess.run(['bash', '-c', script], env=env, capture_output=True).returncode == 0, expected)

    def test_unaffected_signing_never_runs(self):
        for name, signing in [('android', 'production-release'), ('ios', 'signed_production_ipa')]:
            context = {'needs': {'scope': {'outputs': {name + '_release': 'false'}}},
                       'vars': {'FCA_PROD_SIGN_ENABLED': 'true'},
                       'github': {'event_name': 'push', 'ref': 'refs/heads/main',
                                  'repository': 'michaelS1305/family-car-agent'}}
            self.assertFalse(evaluate(self.workflows[name]['jobs'][signing]['if'], context))

    def test_dependency_caches_and_retries(self):
        jobs = self.workflows['android']['jobs']
        for name in ('android', 'production-release'):
            java = next(s for s in jobs[name]['steps'] if s.get('uses') == 'actions/setup-java@v5')
            self.assertEqual(java['with']['cache'], 'gradle')
            self.assertIn('android/gradle/wrapper/gradle-wrapper.properties', java['with']['cache-dependency-path'])
        for job in jobs.values():
            for step in job['steps']:
                self.assertNotIn('.m2', str(step.get('with', {}).get('path', '')))
                self.assertFalse(step.get('uses', '').startswith('actions/cache@'))
        self.assertEqual(str(jobs['android']).count('android_gradle_retry.py'), 2)

    def test_manual_upload_workflow_syntax(self):
        # Upload-only changes still receive local syntax validation, never an upload/build.
        workflow = yaml.load((ROOT / 'workflows/ios-testflight-manual.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow['on']), {'workflow_dispatch'})
        for job in workflow['jobs'].values():
            for step in job.get('steps', []):
                if 'run' in step:
                    subprocess.run(['bash', '-n'], input=step['run'], text=True, check=True, capture_output=True)

    def test_main_signing_rejects_other_repository(self):
        for name, signing in [('android','production-release'), ('ios','signed_production_ipa')]:
            context={'github': {'event_name':'push','ref':'refs/heads/main','repository':'untrusted/fork'},
                     'vars': {'FCA_PROD_SIGN_ENABLED':'true'},
                     'needs': {'scope': {'outputs': {name+'_release':'true'}}}}
            self.assertFalse(evaluate(self.workflows[name]['jobs'][signing]['if'],context))

    def test_unexpected_signing_failure_never_passes_noop(self):
        for name, variable in [('android','SIGNING'),('ios','PRODUCTION_SIGNING'),('ios','DEVELOPMENT_SIGNING')]:
            script=self.workflows[name]['jobs']['required']['steps'][0]['run']
            for result in ('failure','cancelled',''):
                env=dict(os.environ,SCOPE_RESULT='success',VALIDATE='false',VALIDATION='skipped',RELEASE='false',
                         PRODUCTION='true',SIGNING='skipped',PRODUCTION_SIGNING='skipped',DEVELOPMENT_SIGNING='skipped')
                env[variable]=result
                self.assertNotEqual(subprocess.run(['bash','-c',script],env=env,capture_output=True).returncode,0)

    def test_upload_only_scope_to_required_checks_and_no_upload(self):
        scope=classify(['.github/workflows/ios-testflight-manual.yml'])
        outputs={f'{c}_{field}':str(state[field]).lower() for c,state in scope.items()
                 for field in ('validation','release')}
        for event, ref, base in [('push','refs/heads/main',''), ('push','refs/heads/develop',''),
                                 ('pull_request','refs/pull/1/merge','main'),
                                 ('pull_request','refs/pull/1/merge','develop')]:
            context={'github': {'event_name':event,'ref':ref,'base_ref':base,
                               'repository':'michaelS1305/family-car-agent',
                               'event':{'pull_request':{'draft':False,'head':{'ref':'develop',
                                        'repo':{'full_name':'michaelS1305/family-car-agent'}}}}},
                     'vars':{'FCA_PROD_SIGN_ENABLED':'true','FCA_DEV_SIGN_ENABLED':'true',
                             'FCA_TESTFLIGHT_UPLOAD_ENABLED':'true'},
                     'needs':{'scope':{'result':'success','outputs':outputs}}}
            for c in ('android','ios','backend','web'):
                jobs=self.workflows[c]['jobs']
                validation=c if c in ('android','ios') else c+'_validation'
                self.assertFalse(evaluate(jobs[validation]['if'],context))
                for signing in ({'android':['production-release'],
                                  'ios':['signed_dev_ipa','signed_production_ipa']}.get(c,[])):
                    self.assertFalse(evaluate(jobs[signing]['if'],context))
                gate=jobs['required' if c in ('android','ios') else c]['steps'][0]['run']
                env=dict(os.environ,SCOPE_RESULT='success',VALIDATE=outputs[c+'_validation'],
                         RELEASE=outputs[c+'_release'],VALIDATION='skipped',SIGNING='skipped',
                         PRODUCTION_SIGNING='skipped',DEVELOPMENT_SIGNING='skipped',
                         PRODUCTION=str(base=='main' or ref=='refs/heads/main').lower())
                self.assertEqual(subprocess.run(['bash','-c',gate],env=env,capture_output=True).returncode,0)
            context['needs'].update({'ios':{'result':'skipped'},'signed_production_ipa':{'result':'skipped'},
                                     'required':{'result':'success'}})
            self.assertFalse(evaluate(self.workflows['ios']['jobs']['testflight']['if'],context))

    def test_verified_runtime_precedes_tests_and_reports_survive_failure(self):
        steps=self.workflows['android']['jobs']['android']['steps']
        prepare=next(i for i,s in enumerate(steps) if s.get('name')=='Prepare verified Robolectric SDK runtimes')
        for i,step in enumerate(steps):
            if 'android_gradle_retry.py' in step.get('run',''):
                self.assertLess(prepare,i)
                self.assertIn('--init-script ../.github/robolectric-offline.init.gradle',step['run'])
                self.assertIn('--info',step['run'])
                self.assertNotIn('continue-on-error',step)
        reports=next(s for s in steps if s.get('name')=='Preserve Android test reports')
        self.assertEqual(reports['if'],'always()')
        self.assertIn('test-results/**/TEST-*.xml',reports['with']['path'])
        self.assertIn('reports/tests/**',reports['with']['path'])


if __name__ == '__main__':
    unittest.main()

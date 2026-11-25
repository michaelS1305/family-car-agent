"""Scope regression tests use synthetic Git output and actual local Git history; no network."""
import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch
import os
from component_scope import main
import unittest
from component_scope import classify, changed_paths

class ScopeTests(unittest.TestCase):
    def assert_scope(self, paths, validate, release, complete=True):
        result = classify(paths, complete)
        self.assertEqual({c for c,s in result.items() if s['validation']}, set(validate))
        self.assertEqual({c for c,s in result.items() if s['release']}, set(release))
        return result

    def test_component_matrix(self):
        for path, component in [('android/app/build.gradle.kts','android'), ('ios/Sources/App.swift','ios'),
                                ('website/src/Contact.tsx','web'), ('backend/tests/test_worker.py','backend')]:
            with self.subTest(path=path): self.assert_scope([path], [component], [component])

    def test_shared_api(self):
        self.assert_scope(['backend/auth.py'], ['backend','android','ios','web'], ['backend'])
        self.assert_scope(['backend/contact_api.py'], ['backend','web'], ['backend'])

    def test_database(self):
        self.assert_scope(['supabase/manual_migrations/new.sql'], ['backend','android','ios'], ['backend'])

    def test_upload_only(self):
        self.assert_scope(['.github/workflows/ios-testflight-manual.yml'], [], [])

    def test_shared_assets(self):
        self.assert_scope(['assets/branding/logo.png'], ['android','ios','web'], ['android','ios','web'])

    def test_workflow(self):
        self.assert_scope(['.github/workflows/ios.yml'], ['ios'], ['ios'])
        self.assert_scope(['.github/component_scope.py'], ['android','ios','backend','web'], ['android','ios','backend','web'])

    def test_unknown_and_incomplete(self):
        for paths, complete in [(['unknown.conf'], True), ([], False), (['website/src/App.tsx'],False)]:
            self.assert_scope(paths, ['android','ios','backend','web'], ['android','ios','backend','web'], complete)

    def test_pr91(self):
        paths=['backend/device_api.py','backend/take_session_metadata.py','backend/TAKE_SESSION_METADATA.md',
               'backend/tests/test_take_session_metadata.py','ios/Sources/App.swift',
               'supabase/manual_migrations/2026112401_take_session_metadata.sql']
        self.assert_scope(paths, ['backend','android','ios'], ['backend','ios'])

    def test_deleted_renamed_and_no_file_limit(self):
        raw=b'R100\0ios/old.swift\0website/new.ts\0D\0android/old.kt\0'+b'M\0backend/tests/test_a.py\0'*400
        event={'before':'a'*40,'after':'b'*40}
        paths, complete=changed_paths('push',event,lambda *args:raw)
        self.assertTrue(complete)
        self.assertEqual(len(paths),403)
        self.assert_scope(paths,['android','ios','web','backend'],['android','ios','web','backend'])

    def test_malformed_missing_history_and_zero_before(self):
        for raw in [b'M\0', b'R100\0old\0', b'garbage\0', b'M\0../escape\0']:
            self.assertFalse(changed_paths('push',{'before':'a'*40,'after':'b'*40},lambda *a:raw)[1])
        self.assertFalse(changed_paths('push',{'before':'0'*40,'after':'b'*40})[1])
        self.assertFalse(changed_paths('pull_request',{})[1])
        self.assertFalse(changed_paths('workflow_dispatch',{})[1])
        def broken(*args): raise subprocess.CalledProcessError(1,args)
        self.assertFalse(changed_paths('push',{'before':'a'*40,'after':'b'*40},broken)[1])

    def test_real_git_pr_push_equivalence(self):
        with tempfile.TemporaryDirectory() as d:
            def git(*args): return subprocess.check_output(['git','-C',d,*args],stderr=subprocess.DEVNULL)
            git('init'); git('config','user.name','Fixture'); git('config','user.email','fixture@example.invalid')
            p=Path(d)/'ios'; p.mkdir(); (p/'old.swift').write_text('old')
            git('add','ios'); git('commit','-m','base'); base=git('rev-parse','HEAD').decode().strip()
            (p/'old.swift').rename(p/'new.swift'); git('add','-A'); git('commit','-m','rename')
            head=git('rev-parse','HEAD').decode().strip()
            push=changed_paths('push',{'before':base,'after':head},git)
            pr=changed_paths('pull_request',{'pull_request':{'base':{'sha':base},'head':{'sha':head}}},git)
            self.assertEqual(pr,push); self.assertTrue(pr[1]); self.assertEqual(set(pr[0]),{'ios/old.swift','ios/new.swift'})

    def test_github_outputs_and_explanation(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d); event=d/'event.json'; output=d/'output'; summary=d/'summary'
            event.write_text('{}')
            with patch.dict(os.environ, GITHUB_EVENT_PATH=str(event), GITHUB_EVENT_NAME='push',
                            GITHUB_OUTPUT=str(output), GITHUB_STEP_SUMMARY=str(summary)):
                with patch('component_scope.changed_paths', return_value=(['.github/workflows/ios-testflight-manual.yml'], True)):
                    main()
            self.assertEqual(len(output.read_text().splitlines()), 8)
            self.assertTrue(all(line.endswith('=false') for line in output.read_text().splitlines()))
            self.assertIn('unaffected_by_complete_diff', summary.read_text())

    def test_upload_change_does_not_mask_other_changes(self):
        self.assert_scope(['.github/workflows/ios-testflight-manual.yml','android/app/src/main/App.kt'], ['android'], ['android'])

    def test_divergent_branches_and_merge_push(self):
        with tempfile.TemporaryDirectory() as d:
            def git(*args): return subprocess.check_output(['git','-C',d,*args],stderr=subprocess.DEVNULL)
            def commit(path, text):
                p=Path(d)/path; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(text)
                git('add','--',path); git('commit','-m','fixture')
                return git('rev-parse','HEAD').decode().strip()
            git('init','-b','base'); git('config','user.name','Fixture'); git('config','user.email','fixture@example.invalid')
            root=commit('README.md','base')
            git('checkout','-b','feature'); head=commit('ios/new.swift','ios')
            git('checkout','base'); base=commit('android/new.kt','android')
            paths,complete=changed_paths('pull_request',{'pull_request':{'base':{'sha':base},'head':{'sha':head}}},git)
            self.assertTrue(complete); self.assertEqual(paths,['ios/new.swift'])
            self.assert_scope(paths,['ios'],['ios'])
            git('merge','--no-ff','feature','-m','merge fixture')
            merged=git('rev-parse','HEAD').decode().strip()
            self.assertEqual(len(git('rev-list','--parents','-n','1',merged).decode().split()),3)
            self.assertEqual(changed_paths('push',{'before':base,'after':merged},git),(paths,True))
            all_paths,complete=changed_paths('push',{'before':root,'after':merged},git)
            self.assertTrue(complete); self.assert_scope(all_paths,['android','ios'],['android','ios'])

    def test_changed_pr_base_recomputes_merge_base(self):
        with tempfile.TemporaryDirectory() as d:
            def git(*args): return subprocess.check_output(['git','-C',d,*args],stderr=subprocess.DEVNULL)
            def commit(path):
                p=Path(d)/path; p.parent.mkdir(parents=True,exist_ok=True); p.write_text('fixture')
                git('add','--',path); git('commit','-m','fixture')
                return git('rev-parse','HEAD').decode().strip()
            git('init','-b','base'); git('config','user.name','Fixture'); git('config','user.email','fixture@example.invalid')
            old_base=commit('README.md')
            git('checkout','-b','feature'); new_base=commit('android/new.kt'); head=commit('ios/new.swift')
            def compare(base):
                return changed_paths('pull_request',{'pull_request':{'base':{'sha':base},'head':{'sha':head}}},git)
            paths,complete=compare(old_base); self.assertTrue(complete)
            self.assert_scope(paths,['android','ios'],['android','ios'])
            paths,complete=compare(new_base); self.assertTrue(complete)
            self.assert_scope(paths,['ios'],['ios'])

    def test_detection_failure_flows_to_conservative_scope(self):
        def missing(*args): raise subprocess.CalledProcessError(128,args)
        paths,complete=changed_paths('push',{'before':'a'*40,'after':'b'*40},missing)
        self.assertFalse(complete)
        self.assert_scope(paths,['android','ios','backend','web'],['android','ios','backend','web'],complete)

    def test_runtime_preparation_only_affects_android_validation(self):
        self.assert_scope(['.github/'+name for name in ('prepare_robolectric_runtime.py','test_robolectric_runtime.py',
                          'robolectric_runtime.json','robolectric-offline.init.gradle')],['android'],[])

if __name__=='__main__': unittest.main()

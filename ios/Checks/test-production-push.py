"""Production build policy tests using synthetic public plist/profile data only."""
import datetime as dt
import importlib.util
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
import firebase_prod_config as firebase
import firebase_dev_config as dev


def module(name, file):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file))
    value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


wrapper=module('wrapper','app-intents-poc.py')
sign=module('sign','sign-fca-dev.py')
CONFIG={'BUNDLE_ID':'com.familycaragent.app','PROJECT_ID':'family-car-agent',
        'GCM_SENDER_ID':'249909620080','GOOGLE_APP_ID':'1:249909620080:ios:12c8182ee0db3d93ee33b5'}


class ProductionChecks(unittest.TestCase):
    def test_exact_firebase_identity_no_dev_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'GoogleService-Info.plist'
            path.write_bytes(plistlib.dumps(CONFIG))
            firebase.validate(path)
            with self.assertRaises(ValueError): dev.validate(path)
            for field in CONFIG:
                path.write_bytes(plistlib.dumps({**CONFIG,field:'wrong'}))
                with self.assertRaises(ValueError): firebase.validate(path)
            path.write_bytes(plistlib.dumps({**CONFIG,'PROJECT_ID':'family-car-agent-push'}))
            with self.assertRaises(ValueError): firebase.validate(path)

    def test_release_wrapper_and_injected_public_configuration(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,{'FCA_IOS_PROD_SUPABASE_PUBLISHABLE_KEY':'sb_publishable_synthetic'}):
            root=Path(temp); config=root/'GoogleService-Info.plist'
            config.write_bytes(plistlib.dumps(CONFIG)); output=root/'wrapper'
            wrapper.generate(Path(__file__).resolve().parents[1],output,firebase_config=config,production=True)
            project=plistlib.loads((output/'FCAIntentPoC.xcodeproj/project.pbxproj').read_bytes())
            settings=[o['buildSettings'] for o in project['objects'].values() if o['isa']=='XCBuildConfiguration' and o['buildSettings']]
            self.assertEqual(len(settings),1)
            self.assertEqual(settings[0]['PRODUCT_BUNDLE_IDENTIFIER'],'com.familycaragent.app')
            self.assertEqual(settings[0]['MARKETING_VERSION'],'1.0.0')
            self.assertEqual(settings[0]['CURRENT_PROJECT_VERSION'],'1')
            self.assertEqual(settings[0]['SWIFT_ACTIVE_COMPILATION_CONDITIONS'],'FCA_PRODUCTION')
            self.assertEqual(settings[0]['SWIFT_OPTIMIZATION_LEVEL'],'-O')
            info=plistlib.loads((output/'Production-Info.plist').read_bytes())
            self.assertEqual(info['FCAEnvironment'],'production')
            self.assertEqual(info['FCASupabasePublishableKey'],'sb_publishable_synthetic')
            self.assertEqual(info['CFBundleURLTypes'][0]['CFBundleURLSchemes'],['com.familycaragent.app'])
            self.assertFalse(info['FirebaseMessagingAutoInitEnabled'])
            self.assertFalse(info['FirebaseAppDelegateProxyEnabled'])
            self.assertIn('remote-notification',info['UIBackgroundModes'])
            entitlements=plistlib.loads((output/'Production.entitlements').read_bytes())
            self.assertEqual(entitlements['aps-environment'],'production')
            self.assertEqual(entitlements['com.apple.developer.applesignin'],['Default'])
            with self.assertRaises(ValueError):
                wrapper.generate(Path(__file__).resolve().parents[1],root/'probe',probe=True,production=True)

    def test_production_metadata_requires_product_actions_and_excludes_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); app=root/'FamilyCarAgent.app'; app.mkdir()
            (app/'GoogleService-Info.plist').write_bytes(plistlib.dumps(CONFIG))
            (app/'Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier':'com.familycaragent.app','FCAEnvironment':'production',
                'CFBundleDisplayName':'Family Car Agent','UILaunchScreen':{},
                'CFBundleIcons':{'CFBundlePrimaryIcon':{'CFBundleIconName':'AppIcon','CFBundleIconFiles':['AppIcon60x60']}}}))
            (app/'Assets.car').write_bytes(b'synthetic')
            (app/'AppIcon60x60@2x.png').write_bytes(b'synthetic')
            metadata=app/'Metadata.appintents'; metadata.mkdir()
            actions=metadata/'extract.actionsdata'
            for content in [b'', b'FCATakeVehicleIntent',
                    b'FCATakeVehicleIntent FCAReturnVehicleIntent FCAConnectionTestIntent',
                    b'FCATakeVehicleIntent FCAReturnVehicleIntent FCATestOfflineUploadIntent']:
                actions.write_bytes(content)
                with self.assertRaises(ValueError): wrapper.verify(app,root/'report.json',production=True)
            actions.write_bytes(b'FCATakeVehicleIntent FCAReturnVehicleIntent')
            wrapper.verify(app,root/'report.json',production=True)

    def profile(self):
        return {'Name':'Synthetic App Store profile','TeamIdentifier':[sign.TEAM],
            'Platform':['iOS'],'ExpirationDate':dt.datetime.now()+dt.timedelta(days=1),
            'DeveloperCertificates':[b'synthetic'],
            'Entitlements':{'aps-environment':'production','get-task-allow':False,
                'com.apple.developer.applesignin':['Default'],
                'application-identifier':sign.TEAM+'.com.familycaragent.app',
                'com.apple.developer.team-identifier':sign.TEAM,
                'keychain-access-groups':[sign.TEAM+'.com.familycaragent.app']}}

    def test_app_store_profile_rejects_dev_adhoc_enterprise_and_wrong_identity(self):
        sign.verify_profile(self.profile(),production=True)
        for field,value in [('ProvisionedDevices',['synthetic']),('ProvisionsAllDevices',True),
                ('TeamIdentifier',['wrong']),('ExpirationDate',dt.datetime.now()-dt.timedelta(days=1))]:
            profile=self.profile(); profile[field]=value
            with self.assertRaises(sign.SignError): sign.verify_profile(profile,production=True)
        for field,value in [('aps-environment','development'),('get-task-allow',True),
                ('application-identifier',sign.TEAM+'.com.familycaragent.app.dev'),
                ('com.apple.developer.applesignin',[])]:
            profile=self.profile(); profile['Entitlements'][field]=value
            with self.assertRaises(sign.SignError): sign.verify_profile(profile,production=True)
        with self.assertRaises(sign.SignError): sign.verify_profile(self.profile())

    def test_production_signing_requires_manual_flag(self):
        with patch.object(sign.sys,'platform','darwin'), patch.dict(os.environ,{
                'GITHUB_EVENT_NAME':'push','GITHUB_REF':'refs/heads/develop','FCA_PROD_SIGN_ENABLED':'true'}):
            with self.assertRaisesRegex(sign.SignError,'explicit manual approval'):
                sign.sign(Path('unused'),Path('unused'),production=True)

    def test_production_signing_waits_for_validation_and_offline_recovery_checks(self):
        workflow = (Path(__file__).resolve().parents[2] / '.github/workflows/ios.yml').read_text()
        production = workflow.split('  signed_production_ipa:', 1)[1]
        self.assertIn('    needs: ios\n', production)
        validation = workflow.split('  signed_dev_ipa:', 1)[0]
        for script in ('run-vehicle-queue-checks.sh', 'run-vehicle-sync-checks.sh', 'run-native-device-setup-checks.sh'):
            self.assertIn('bash Checks/' + script, validation)


if __name__ == '__main__': unittest.main()

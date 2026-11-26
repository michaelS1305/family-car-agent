"""Permanent native RETURN configuration/contract checks; no app build or network."""
import importlib.util
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'ios/Sources/FamilyCarAgent'
spec = importlib.util.spec_from_file_location('wrapper', Path(__file__).with_name('app-intents-poc.py'))
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)

class NativeReturnChecks(unittest.TestCase):
    def test_effective_development_and_production_plists(self):
        from firebase_dev_config import BUNDLE, PROJECT, SENDER
        configurations = [(False, BUNDLE, PROJECT, SENDER, f'1:{SENDER}:ios:abcdef'),
                          (True, 'com.familycaragent.app', 'family-car-agent', '249909620080', '1:249909620080:ios:12c8182ee0db3d93ee33b5')]
        for production,bundle,project,sender,app in configurations:
            with self.subTest(production=production), tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'FCA_IOS_PROD_SUPABASE_PUBLISHABLE_KEY':'sb_publishable_synthetic'}):
                root=Path(temp); firebase=root/'GoogleService-Info.plist'
                firebase.write_bytes(plistlib.dumps(dict(BUNDLE_ID=bundle,PROJECT_ID=project,GCM_SENDER_ID=sender,GOOGLE_APP_ID=app)))
                output=root/'wrapper'
                wrapper.generate(ROOT/'ios',output,firebase_config=firebase,production=production)
                project_data=plistlib.loads((output/'FCAIntentPoC.xcodeproj/project.pbxproj').read_bytes())
                settings=next(o['buildSettings'] for o in project_data['objects'].values() if o.get('buildSettings',{}).get('SDKROOT'))
                info=plistlib.loads(Path(settings['INFOPLIST_FILE']).read_bytes())
                self.assertEqual(set(info['UIBackgroundModes']),{'location','remote-notification'})
                purpose=info['NSLocationWhenInUseUsageDescription']
                self.assertIn('החזרת רכב',purpose); self.assertIn('ברקע',purpose)
                self.assertFalse(any('Always' in key for key in info))
                sources=' '.join(str(o.get('path','')) for o in project_data['objects'].values())
                self.assertIn('ReturnLocationAcquisition.swift',sources)
                self.assertNotIn('NativeLocationPOC',sources)

    def test_intent_no_location_parameter_or_prompt(self):
        intent=(SRC/'OfflineEvents/VehicleAppIntents.swift').read_text(encoding='utf-8')
        self.assertNotIn('CLPlacemark',intent)
        self.assertNotIn('Current Location',intent)
        self.assertNotIn('requestWhenInUseAuthorization',intent)
        self.assertLess(intent.index('prepareNativeReturn(selection:'),intent.index('await acquisition.acquire()'))
        self.assertLess(intent.index('await acquisition.acquire()'),intent.index('runtime.recordNativeReturn'))
        self.assertIn('static let openAppWhenRun = false',intent)

    def test_native_adapter_lifecycle_and_no_network(self):
        adapter=(SRC/'OfflineEvents/ReturnLocationAcquisition.swift').read_text(encoding='utf-8')
        for value in ['@MainActor','@preconcurrency CLLocationManagerDelegate','ContinuousClock','startUpdatingLocation()', 'stopUpdatingLocation()', 'withTaskCancellationHandler','candidate = nil','fix.timestamp']:
            self.assertIn(value,adapter)
        for value in ['URLSession','CLGeocoder','requestWhenInUseAuthorization','requestAlwaysAuthorization','requestTemporaryFullAccuracyAuthorization','VehicleEventQueue','manager.location']:
            self.assertNotIn(value,adapter)
        self.assertNotIn('#if DEBUG',adapter)
        runtime=(SRC/'OfflineEvents/VehicleSessionRuntime.swift').read_text(encoding='utf-8')
        committed=runtime.index('let event = try await prepared.queue.commitReturn')
        callback=runtime.index('onCommit()',committed)
        scheduling=runtime.index('try attach(prepared.snapshot.context',committed)
        self.assertLess(committed,callback); self.assertLess(callback,scheduling)

    def test_permission_sequencing_and_no_tracking(self):
        push=(SRC/'Push/NativePushService.swift').read_text(encoding='utf-8')
        start=push.index('defer { if current(ticket) { LocationPermissionService.shared.notificationsFinished() } }')
        request=push.index('await center.requestAuthorization')
        error=push.index('state.errorCategory = "notification_permission"; return',request)
        self.assertLess(start,request)
        self.assertLess(request,error)
        self.assertEqual(push.count('LocationPermissionService.shared.notificationsFinished()'),1)
        permission=(SRC/'OfflineEvents/LocationPermissionService.swift').read_text(encoding='utf-8')
        self.assertIn('UIApplication.didBecomeActiveNotification',permission)
        self.assertIn('applicationState == .active',permission)
        self.assertNotIn('startUpdatingLocation',permission)
        self.assertNotIn('requestAlways',permission)

    def test_ci_executes_permanent_checks(self):
        workflow=(ROOT/'.github/workflows/ios.yml').read_text(encoding='utf-8')
        self.assertIn('bash Checks/run-native-return-location-checks.sh',workflow)
        runner=Path(__file__).with_name('run-native-return-location-checks.sh').read_text()
        self.assertIn('test-native-return-location.py',runner)
        self.assertNotIn('native-offline-location-poc',workflow)

if __name__ == '__main__': unittest.main()

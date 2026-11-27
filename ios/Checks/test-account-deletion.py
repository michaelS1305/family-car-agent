"""Contract/privacy guards complement executable Swift and PostgreSQL checks."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]/'Sources/FamilyCarAgent'
class DeletionContractTests(unittest.TestCase):
    def test_release_diagnostics_only_emit_fixed_enum_fields(self):
        text=(ROOT/'OfflineEvents/VehicleEventQueue.swift').read_text(encoding='utf-8')
        diagnostic=text[text.index('enum DeviceSetupDiagnostics'):text.index('/// A durable projection')]
        self.assertNotIn('#if DEBUG',diagnostic)
        self.assertIn('Stage: String',diagnostic); self.assertIn('Reason: String',diagnostic)
        self.assertNotIn('localizedDescription',diagnostic); self.assertNotIn('userInfo',diagnostic); self.assertIn('Code: Int',diagnostic)
        self.assertIn('stage.rawValue',diagnostic); self.assertIn('reason.rawValue',diagnostic)
    def test_preflight_rejection_reasons_and_origins(self):
        text=(ROOT/'OfflineEvents/VehicleSessionRuntime.swift').read_text(encoding='utf-8')
        for reason in ['storage','cancelled','epoch','generation','sessionMissing','owner','inactive','user','family']:
            self.assertIn('reject(.'+reason+')',text)
        self.assertIn('.authorization, .denyBindings',text)
        self.assertIn('.authorization, .invalidation',text)
    def test_new_client_requires_new_request_route(self):
        text=(ROOT/'Auth/AccountDeletionCleanup.swift').read_text(encoding='utf-8')
        self.assertIn('path:"request"',text); self.assertIn('deletion-status-v1',text)
        self.assertIn('SecRandomCopyBytes',text); self.assertIn('count:32',text)
        self.assertIn('kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly',text)
        self.assertNotIn('print(',text)
    def test_scoped_cleanup_and_secure_delete(self):
        text=(ROOT/'OfflineEvents/VehicleEventQueue.swift').read_text(encoding='utf-8')
        self.assertIn('PRAGMA secure_delete=ON',text)
        self.assertIn('PRAGMA journal_mode=DELETE',text)
        self.assertIn('DELETE FROM events WHERE context=?',text)
        self.assertIn('deleted_device_',text)
    def test_background_cancellation_precedes_cleanup(self):
        text=(ROOT/'Auth/AccountDeletionCleanup.swift').read_text(encoding='utf-8')
        self.assertLess(text.index('confirmation(record:record,reply:reply,save:save)'),text.index('try await cancel(confirmed)'))
        self.assertLess(text.index('try await cancel(confirmed)'),text.index('apply(record:confirmed'))
        transport=(ROOT/'OfflineEvents/VehicleBackgroundUploadTransport.swift').read_text(encoding='utf-8')
        self.assertIn('session.invalidateAndCancel()',transport)
        self.assertIn('didBecomeInvalidWithError',transport)
        self.assertIn('seconds(15)',text); self.assertIn('finish(failed:error != nil)',transport)
    def test_new_checks_are_in_existing_ci_entry(self):
        self.assertIn('Checks/run-account-deletion-checks.sh',(ROOT.parents[1]/'Checks/run-ci-checks.sh').read_text(encoding='utf-8'))
if __name__=='__main__': unittest.main()

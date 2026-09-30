package il.fca.companion

import android.app.Application
import android.bluetooth.BluetoothDevice
import android.companion.CompanionDeviceManager
import android.content.ComponentName
import android.content.pm.PackageManager
import android.os.Build
import il.fca.companion.data.LocalStore
import il.fca.companion.detector.AclReceiver
import il.fca.companion.detector.DetectorEvents
import il.fca.companion.detector.DetectorPlatform
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35, 36], application = Application::class)
class DetectorCompatibilityTest {
    private val context get() = RuntimeEnvironment.getApplication()
    private fun store(): LocalStore {
        context.deleteDatabase("fca.db")
        return LocalStore(context).apply {
            installation("owner"); registered("owner", "00000000-0000-4000-8000-000000000001")
            activate("owner"); associate("owner", "vehicle", "AA:BB:CC:DD:EE:FF", 7)
        }
    }

    @Test fun exactlyOneDetectorEnabledByInstalledSdk() {
        val flags = PackageManager.MATCH_DISABLED_COMPONENTS
        val receiver = context.packageManager.getReceiverInfo(ComponentName(context, AclReceiver::class.java), flags)
        // String name deliberately avoids loading the API 36 service on API 35.
        val service = context.packageManager.getServiceInfo(ComponentName(context,
            "il.fca.companion.detector.PresenceService"), flags)
        assertEquals(Build.VERSION.SDK_INT == 35, receiver.enabled)
        assertEquals(Build.VERSION.SDK_INT >= 36, service.enabled)
        assertEquals("android.permission.BIND_COMPANION_DEVICE_SERVICE", service.permission)
        if (Build.VERSION.SDK_INT == 35) {
            val manager = context.getSystemService(CompanionDeviceManager::class.java)
            DetectorPlatform.start(manager, 7)
            DetectorPlatform.stop(manager, 7)
        }
    }

    @Test fun aclIsBoundClassicOnlyAndDisabledOn36() {
        store().use { store ->
            val connect = BluetoothDevice.ACTION_ACL_CONNECTED
            val classic = BluetoothDevice.TRANSPORT_BREDR
            assertEquals(if (Build.VERSION.SDK_INT == 35) 7 to true else null,
                AclReceiver.resolve(store, connect, "aa:bb:cc:dd:ee:ff", classic))
            assertNull(AclReceiver.resolve(store, connect, "AA:BB:CC:DD:EE:00", classic))
            assertNull(AclReceiver.resolve(store, connect, "AA:BB:CC:DD:EE:FF", BluetoothDevice.TRANSPORT_LE))
            assertNull(AclReceiver.resolve(store, connect, "AA:BB:CC:DD:EE:FF", BluetoothDevice.TRANSPORT_AUTO))
            assertNull(AclReceiver.resolve(store, "unexpected", "AA:BB:CC:DD:EE:FF", classic))
            store.activate(null)
            assertNull(AclReceiver.resolve(store, connect, "AA:BB:CC:DD:EE:FF", classic))
        }
    }

    @Test fun platformEvidenceUsesSharedTakeReturnGraceAndDuplicateLatch() {
        store().use { store ->
            var kicks = 0
            var returns = 0
            fun event(connected: Boolean) {
                val mapped = if (Build.VERSION.SDK_INT == 35)
                    AclReceiver.resolve(store, if (connected) BluetoothDevice.ACTION_ACL_CONNECTED
                        else BluetoothDevice.ACTION_ACL_DISCONNECTED,
                        "AA:BB:CC:DD:EE:FF", BluetoothDevice.TRANSPORT_BREDR)!!
                else 7 to connected
                DetectorEvents.record(store, mapped.first, mapped.second, { kicks++ }, { returns++ })
            }
            event(true)
            val take = store.next("owner")!!
            event(true)
            assertEquals(1, kicks)
            assertEquals(take, store.next("owner"))
            event(false)
            val candidate = store.candidates("owner").single()
            assertEquals(take.id, candidate.take)
            assertEquals(1, returns)
            event(false)
            assertEquals(candidate, store.candidates("owner").single())
            assertEquals(1L, store.pending("owner"))
            event(true)
            assertTrue(store.candidates("owner").isEmpty())
            assertFalse(store.queueReturn(candidate, "{}", candidate.due, candidate.elapsedDue))
            assertEquals(2, kicks)
            assertEquals(take, store.next("owner"))
            assertFalse(store.diagnostics().contains("AA:BB"))
        }
    }
}

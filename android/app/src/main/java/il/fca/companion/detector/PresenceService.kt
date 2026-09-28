package il.fca.companion.detector

import android.companion.CompanionDeviceService
import android.companion.DevicePresenceEvent
import il.fca.companion.FcaApplication
import il.fca.companion.delivery.DeliveryWorker

class PresenceService : CompanionDeviceService() {
    override fun onDevicePresenceEvent(event: DevicePresenceEvent) {
        val connected = when (event.event) {
            DevicePresenceEvent.EVENT_BT_CONNECTED -> true
            DevicePresenceEvent.EVENT_BT_DISCONNECTED -> false
            else -> return // BLE proximity is NOT a physical Classic connection.
        }
        val app = application as FcaApplication
        // Tiny local transaction, no network. Return only after durable recording.
        try {
            val queued = app.store.observe(event.associationId, connected)
            app.store.diagnostic(if (connected) "bluetooth_connected" else "bluetooth_disconnected_no_return")
            if (queued) DeliveryWorker.enqueue(this)
        } catch (_: Exception) {
            // Never crash the system-bound service or log identity/Bluetooth data.
            runCatching { app.store.diagnostic("detector_storage_error") }
        }
    }
}

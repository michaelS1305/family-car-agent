package il.fca.companion.detector

import android.companion.CompanionDeviceService
import android.companion.DevicePresenceEvent
import androidx.annotation.RequiresApi

@RequiresApi(36)
class PresenceService : CompanionDeviceService() {
    override fun onDevicePresenceEvent(event: DevicePresenceEvent) {
        val connected = when (event.event) {
            DevicePresenceEvent.EVENT_BT_CONNECTED -> true
            DevicePresenceEvent.EVENT_BT_DISCONNECTED -> false
            else -> return // BLE proximity is NOT a physical Classic connection.
        }
        DetectorEvents.record(this, event.associationId, connected)
    }
}

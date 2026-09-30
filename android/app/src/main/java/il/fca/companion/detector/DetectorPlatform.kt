package il.fca.companion.detector

import android.companion.CompanionDeviceManager
import android.companion.ObservingDevicePresenceRequest
import android.os.Build
import androidx.annotation.RequiresApi

object DetectorPlatform {
    fun start(manager: CompanionDeviceManager, associationId: Int) {
        if (Build.VERSION.SDK_INT >= 36) Presence36.start(manager, associationId)
        // API 35 uses manifest ACL broadcasts; association still establishes local identity.
    }

    fun stop(manager: CompanionDeviceManager, associationId: Int) {
        if (Build.VERSION.SDK_INT >= 36) Presence36.stop(manager, associationId)
    }

    // Isolate references to API 36 classes from classes loaded on Android 15.
    @RequiresApi(36)
    private object Presence36 {
        fun start(manager: CompanionDeviceManager, id: Int) = manager.startObservingDevicePresence(
            ObservingDevicePresenceRequest.Builder().setAssociationId(id).build())
        fun stop(manager: CompanionDeviceManager, id: Int) = manager.stopObservingDevicePresence(
            ObservingDevicePresenceRequest.Builder().setAssociationId(id).build())
    }
}

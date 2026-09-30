package il.fca.companion.detector

import android.content.Context
import il.fca.companion.FcaApplication
import il.fca.companion.data.LocalStore
import il.fca.companion.delivery.DeliveryWorker

/** Both platform adapters feed the same durable transition and scheduling path. */
internal object DetectorEvents {
    fun record(store: LocalStore, associationId: Int, connected: Boolean,
               delivery: () -> Unit, returns: () -> Unit) {
        try {
            val queued = store.observe(associationId, connected)
            runCatching { store.diagnostic(if (connected) "bluetooth_connected" else "bluetooth_disconnected") }
            if (queued) delivery()
            if (!connected) returns()
        } catch (_: Exception) {
            runCatching { store.diagnostic("detector_storage_error") }
        }
    }

    fun record(context: Context, associationId: Int, connected: Boolean) {
        val app = context.applicationContext as FcaApplication
        record(app.store, associationId, connected,
            { DeliveryWorker.enqueue(context) }, {
                ReturnWorker.enqueue(context) // Durable safety net, including process loss before start.
                ReturnForegroundService.request(context)
            })
    }
}

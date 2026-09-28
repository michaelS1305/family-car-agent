package il.fca.companion.delivery

import android.content.Context
import androidx.work.*
import il.fca.companion.FcaApplication
import il.fca.companion.net.HttpFailure
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class DeliveryWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val app = applicationContext as FcaApplication
        val owner = app.store.activeOwner() ?: return Result.success()
        try {
            // Account changes never transfer old pending events to the new user.
            if (app.auth.owner() != owner) return Result.retry()
            repeat(32) {
                if (isStopped || app.store.activeOwner() != owner) return Result.retry()
                val event = app.store.next(owner) ?: return Result.success()
                val body = JSONObject().put("event_id", event.id).put("device_sequence", event.sequence)
                    .put("vehicle_ref", event.vehicle).put("occurred_at", event.occurredAt)
                event.evidence?.let { raw ->
                    val evidence = JSONObject(raw)
                    evidence.keys().forEach { body.put(it, evidence.get(it)) }
                }
                val result = JSONObject(app.api.call(owner, "/api/devices/${event.device}/events/${event.type}", "POST", body))
                val kind = result.getString("kind")
                if (kind in setOf("accepted", "retry", "terminal")) {
                    app.store.finish(event.id, kind)
                    app.store.diagnostic("${event.type}_delivery_$kind")
                } else {
                    // Gap/conflict/skew/unavailable never consume a local sequence.
                    app.store.diagnostic("delivery_needs_attention")
                    return Result.retry()
                }
            }
            return Result.retry()
        } catch (e: HttpFailure) {
            app.store.diagnostic("delivery_http_${e.status}")
            return Result.retry()
        } catch (_: Exception) {
            app.store.diagnostic("delivery_auth_or_network_pending")
            return Result.retry()
        }
    }
    companion object {
        private val network = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
        fun enqueue(context: Context) {
            WorkManager.getInstance(context).enqueueUniqueWork("fca-delivery", ExistingWorkPolicy.APPEND_OR_REPLACE,
                OneTimeWorkRequestBuilder<DeliveryWorker>().setConstraints(network)
                    .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS).build())
        }
        fun ensureRecovery(context: Context) {
            // Covers death after SQLite commit but before immediate enqueue.
            WorkManager.getInstance(context).enqueueUniquePeriodicWork("fca-outbox-recovery", ExistingPeriodicWorkPolicy.KEEP,
                PeriodicWorkRequestBuilder<DeliveryWorker>(15, TimeUnit.MINUTES).setConstraints(network).build())
        }
    }
}

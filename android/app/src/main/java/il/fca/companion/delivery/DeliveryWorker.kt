package il.fca.companion.delivery

import android.content.Context
import androidx.work.*
import il.fca.companion.FcaApplication
import il.fca.companion.net.HttpFailure
import il.fca.companion.data.LocalStore
import org.json.JSONObject
import java.util.concurrent.TimeUnit
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

internal enum class DrainOutcome { COMPLETE, RECOVER, MORE }

/** All workers run in the default app process. No SQLite transaction spans HTTP. */
internal object DeliveryDrain {
    private val lock = ReentrantLock(true)
    fun run(store: LocalStore, authOwner: () -> String?, stopped: () -> Boolean,
            send: (String, String, JSONObject) -> String): DrainOutcome = lock.withLock {
        fun diagnostic(category: String) { runCatching { store.diagnostic(category) } }
        val owner = store.activeOwner() ?: return DrainOutcome.COMPLETE
        try {
            if (stopped() || authOwner() != owner) return DrainOutcome.RECOVER
            repeat(32) {
                if (stopped() || store.activeOwner() != owner) return DrainOutcome.RECOVER
                val event = store.next(owner) ?: return DrainOutcome.COMPLETE
                val body = JSONObject().put("event_id", event.id).put("device_sequence", event.sequence)
                    .put("vehicle_ref", event.vehicle).put("occurred_at", event.occurredAt)
                event.evidence?.let { raw ->
                    val evidence = JSONObject(raw)
                    evidence.keys().forEach { body.put(it, evidence.get(it)) }
                }
                val result = JSONObject(send(owner, "/api/devices/${event.device}/events/${event.type}", body))
                val kind = result.getString("kind")
                if (kind in setOf("accepted", "retry", "terminal")) {
                    store.finish(event.id, kind)
                    diagnostic("${event.type}_delivery_$kind")
                } else {
                    diagnostic("delivery_needs_attention")
                    return DrainOutcome.RECOVER
                }
            }
            DrainOutcome.MORE
        } catch (e: HttpFailure) {
            diagnostic("delivery_http_${e.status}" + (e.diagnosticCode?.let { "_$it" } ?: ""))
            DrainOutcome.RECOVER
        } catch (_: Exception) {
            diagnostic("delivery_auth_or_network_pending")
            DrainOutcome.RECOVER
        }
    }
}

class DeliveryWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val app = applicationContext as FcaApplication
        val source = inputData.getString("source").takeIf { it in setOf("kick", "recovery", "periodic") } ?: "legacy_recovery"
        runCatching { app.store.diagnostic("delivery_${source}_started_attempt_$runAttemptCount") }
        return when (DeliveryDrain.run(app.store, { app.auth.owner() }, { isStopped }) { owner, path, body ->
            app.api.call(owner, path, "POST", body)
        }) {
            DrainOutcome.COMPLETE -> Result.success()
            DrainOutcome.MORE -> { enqueue(applicationContext); Result.success() }
            DrainOutcome.RECOVER -> {
                if (source == "kick") {
                    // Finish this kick. Backoff belongs only to an independent recovery chain.
                    WorkManager.getInstance(applicationContext).enqueueUniqueWork("fca-delivery-recovery",
                        ExistingWorkPolicy.APPEND_OR_REPLACE, recoveryRequest()).result.get()
                    Result.success()
                } else Result.retry()
            }
        }
    }
    companion object {
        private val network = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
        internal fun kickRequest() = OneTimeWorkRequestBuilder<DeliveryWorker>()
            .setInputData(workDataOf("source" to "kick")).setConstraints(network)
            .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST).build()
        internal fun recoveryRequest() = OneTimeWorkRequestBuilder<DeliveryWorker>()
            .setInputData(workDataOf("source" to "recovery")).setConstraints(network)
            .setInitialDelay(30, TimeUnit.SECONDS)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS).build()
        fun enqueue(context: Context) {
            // Each persisted event gets an independent durable opportunity. No KEEP
            // or prerequisite chain can swallow a wakeup near another drain's exit.
            WorkManager.getInstance(context).enqueue(kickRequest())
            runCatching { (context.applicationContext as FcaApplication).store.diagnostic("delivery_kick_requested") }
        }
        fun ensureRecovery(context: Context) {
            // Covers death after SQLite commit but before immediate enqueue.
            WorkManager.getInstance(context).enqueueUniquePeriodicWork("fca-outbox-recovery", ExistingPeriodicWorkPolicy.KEEP,
                PeriodicWorkRequestBuilder<DeliveryWorker>(15, TimeUnit.MINUTES).setConstraints(network)
                    .setInputData(workDataOf("source" to "periodic")).build())
        }
    }
}

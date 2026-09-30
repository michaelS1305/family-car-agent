package il.fca.companion.detector

import android.content.Context
import android.location.Location
import android.os.SystemClock
import androidx.work.*
import il.fca.companion.data.LocalStore
import il.fca.companion.data.ReturnCandidate
import java.util.concurrent.TimeUnit

/** Recovery requests the same FGS controller; it never acquires location itself. */
class ReturnWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        ReturnForegroundService.request(applicationContext)
        return Result.success()
    }

    internal data class LocationCheck(val fix: Location? = null, val reason: String? = null)

    companion object {
        internal fun graceElapsed(candidate: ReturnCandidate, now: Long, elapsed: Long): Boolean =
            now >= candidate.due && elapsed >= candidate.elapsedDue

        internal fun homeRadiusFailure(fix: Location, home: Pair<Double, Double>): String? =
            if (insideHome(fix, home)) null else "outside_home_radius"

        internal fun diagnostic(write: (String) -> Unit, category: String) {
            // Observability must never prevent mutation, abandonment or delivery scheduling.
            runCatching { write(category) }
        }

        fun usableFix(fix: Location?, now: Long = System.currentTimeMillis(),
                      elapsedNanos: Long = SystemClock.elapsedRealtimeNanos()): Boolean = fixFailure(fix, now, elapsedNanos) == null

        internal fun fixFailure(fix: Location?, now: Long = System.currentTimeMillis(),
                               elapsedNanos: Long = SystemClock.elapsedRealtimeNanos()): String? {
            if (fix == null) return "location_unavailable"
            val age = elapsedNanos - fix.elapsedRealtimeNanos
            val wallAge = now - fix.time
            return when {
                age < 0 || wallAge < 0 -> "location_timestamp_invalid"
                age > 30_000_000_000L || wallAge > 30_000L -> "location_too_old"
                fix.isMock -> "location_mock"
                !fix.hasAccuracy() -> "location_accuracy_missing"
                !fix.accuracy.isFinite() || fix.accuracy <= 0 -> "location_accuracy_invalid"
                fix.accuracy > 100 -> "location_accuracy_too_low"
                !fix.latitude.isFinite() || fix.latitude !in -90.0..90.0 ||
                    !fix.longitude.isFinite() || fix.longitude !in -180.0..180.0 -> "location_coordinates_invalid"
                else -> null
            }
        }
        fun insideHome(fix: Location, home: Pair<Double, Double>): Boolean {
            val distances = FloatArray(1)
            Location.distanceBetween(fix.latitude, fix.longitude, home.first, home.second, distances)
            return distances[0].isFinite() && distances[0] + fix.accuracy <= 500
        }
        fun enqueue(context: Context) {
            WorkManager.getInstance(context).enqueueUniqueWork("fca-return", ExistingWorkPolicy.APPEND_OR_REPLACE,
                OneTimeWorkRequestBuilder<ReturnWorker>().setInitialDelay(LocalStore.RETURN_GRACE_MS, TimeUnit.MILLISECONDS).build())
        }
        internal fun deferredWorkName(candidate: ReturnCandidate): String = "fca-return-deferred-" +
            java.util.UUID.nameUUIDFromBytes(listOf(candidate.owner, candidate.vehicle, candidate.take,
                candidate.due.toString(), candidate.elapsedDue.toString()).joinToString("\u0000").toByteArray(Charsets.UTF_8))

        fun enqueueDeferred(context: Context, candidate: ReturnCandidate, delayMs: Long) {
            // Replace only this candidate's wakeup, never another candidate or an acquisition.
            // Recovered deadlines are absolute in SQLite; no shared predecessor can delay them.
            WorkManager.getInstance(context).enqueueUniqueWork(deferredWorkName(candidate),
                ExistingWorkPolicy.REPLACE,
                OneTimeWorkRequestBuilder<ReturnWorker>().setInitialDelay(delayMs.coerceAtLeast(1), TimeUnit.MILLISECONDS).build())
        }
        fun recover(context: Context) {
            WorkManager.getInstance(context).enqueueUniquePeriodicWork("fca-return-recovery", ExistingPeriodicWorkPolicy.KEEP,
                PeriodicWorkRequestBuilder<ReturnWorker>(15, TimeUnit.MINUTES).build())
            enqueue(context)
            ReturnForegroundService.request(context) // Process restart must not add another grace period.
        }
    }
}

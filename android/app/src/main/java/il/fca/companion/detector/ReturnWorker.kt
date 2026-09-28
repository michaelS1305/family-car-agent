package il.fca.companion.detector

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationManager
import android.os.CancellationSignal
import android.os.SystemClock
import androidx.work.*
import il.fca.companion.FcaApplication
import il.fca.companion.data.LocalStore
import il.fca.companion.delivery.DeliveryWorker
import org.json.JSONObject
import java.time.Instant
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** One bounded location request per disconnect, not a location tracker. No network constraint. */
class ReturnWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val app = applicationContext as FcaApplication
        val owner = app.store.activeOwner() ?: return Result.success()
        for (candidate in app.store.candidates(owner)) {
            val now = System.currentTimeMillis()
            if (now < candidate.due || SystemClock.elapsedRealtime() < candidate.elapsedDue) continue
            // A delayed background job must not interpret arrival home hours later
            // as evidence for an old disconnect. Fail closed, requiring a new cycle.
            if (now - candidate.due > 300_000) {
                app.store.abandon(candidate); app.store.diagnostic("return_not_created_stale_disconnect"); continue
            }
            app.store.diagnostic("return_home_check_started")
            val home = app.store.home(owner)
            val fix = if (home != null) freshLocation() else null
            if (fix == null || home == null) {
                app.store.abandon(candidate)
                app.store.diagnostic("return_home_check_failed_permission_location_or_home")
                continue
            }
            if (!insideHome(fix, home)) {
                app.store.abandon(candidate); app.store.diagnostic("outside_home_return_not_created"); continue
            }
            if (isStopped) return Result.retry()
            val body = JSONObject().put("take_event_id", candidate.take).put("latitude", fix.latitude)
                .put("longitude", fix.longitude).put("accuracy_m", fix.accuracy.toDouble())
                .put("location_at", Instant.ofEpochMilli(fix.time).toString())
            if (app.store.queueReturn(candidate, body.toString())) {
                app.store.diagnostic("return_queued"); DeliveryWorker.enqueue(applicationContext)
            }
        }
        return Result.success()
    }

    private fun freshLocation(): Location? {
        if (listOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_BACKGROUND_LOCATION)
                .any { applicationContext.checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }) return null
        val cancellation = CancellationSignal()
        return try {
            val manager = applicationContext.getSystemService(LocationManager::class.java)
            val done = CountDownLatch(1)
            var result: Location? = null
            manager.getCurrentLocation(LocationManager.GPS_PROVIDER, cancellation, applicationContext.mainExecutor) {
                result = it; done.countDown()
            }
            if (!done.await(20, TimeUnit.SECONDS) || isStopped) null else result?.takeIf { usableFix(it) }
        } catch (_: Exception) { null } finally { cancellation.cancel() }
    }

    companion object {
        fun usableFix(fix: Location?, now: Long = System.currentTimeMillis(),
                      elapsedNanos: Long = SystemClock.elapsedRealtimeNanos()): Boolean {
            if (fix == null) return false
            val age = elapsedNanos - fix.elapsedRealtimeNanos
            val wallAge = now - fix.time
            return age in 0..30_000_000_000L && wallAge in 0..30_000L && !fix.isMock && fix.hasAccuracy() &&
                fix.accuracy.isFinite() && fix.accuracy > 0 && fix.accuracy <= 100 &&
                fix.latitude.isFinite() && fix.latitude in -90.0..90.0 &&
                fix.longitude.isFinite() && fix.longitude in -180.0..180.0
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
        fun recover(context: Context) {
            WorkManager.getInstance(context).enqueueUniquePeriodicWork("fca-return-recovery", ExistingPeriodicWorkPolicy.KEEP,
                PeriodicWorkRequestBuilder<ReturnWorker>(15, TimeUnit.MINUTES).build())
            enqueue(context)
        }
    }
}

package il.fca.companion

import android.app.Application
import android.location.Location
import android.os.SystemClock
import il.fca.companion.data.LocalStore
import il.fca.companion.detector.DetectorEvents
import il.fca.companion.detector.ReturnWorker
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35, 36], application = Application::class)
class ReturnDiagnosticsTest {
    private fun fix() = Location("gps").apply {
        latitude = 32.0; longitude = 34.0; accuracy = 10f
        time = System.currentTimeMillis(); elapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos()
    }

    @Test fun everyFixValidationHasBoundedReasonAndOriginalBoundary() {
        val now = System.currentTimeMillis()
        val elapsed = SystemClock.elapsedRealtimeNanos()
        fun reason(expected: String?, change: Location.() -> Unit) {
            val value = fix().apply { time = now; elapsedRealtimeNanos = elapsed }.apply(change)
            assertEquals(expected, ReturnWorker.fixFailure(value, now, elapsed))
            assertEquals(expected == null, ReturnWorker.usableFix(value, now, elapsed))
        }
        assertEquals("location_unavailable", ReturnWorker.fixFailure(null))
        reason("location_timestamp_invalid") { time = now + 1 }
        reason("location_timestamp_invalid") { elapsedRealtimeNanos = elapsed + 1 }
        reason("location_too_old") { time = now - 30_001 }
        reason("location_too_old") { elapsedRealtimeNanos = elapsed - 30_000_000_001L }
        reason("location_mock") { isMock = true }
        reason("location_accuracy_missing") { removeAccuracy() }
        for (accuracy in listOf(0f, -1f, Float.NaN, Float.POSITIVE_INFINITY))
            reason("location_accuracy_invalid") { this.accuracy = accuracy }
        reason("location_accuracy_too_low") { accuracy = 100.01f }
        reason("location_coordinates_invalid") { latitude = Double.NaN }
        reason("location_coordinates_invalid") { latitude = 91.0 }
        reason("location_coordinates_invalid") { longitude = 181.0 }
        reason(null) { accuracy = 100f; time = now - 30_000; elapsedRealtimeNanos = elapsed - 30_000_000_000L }
        val valid = fix()
        assertTrue(ReturnWorker.insideHome(valid, 32.0 to 34.0))
        assertFalse(ReturnWorker.insideHome(valid, 33.0 to 34.0))
        assertEquals("outside_home_radius", ReturnWorker.homeRadiusFailure(valid, 33.0 to 34.0))
        assertNull(ReturnWorker.homeRadiusFailure(valid, 32.0 to 34.0))
    }

    @Test fun cacheReasonsPreserve24HourPolicy() {
        val context = RuntimeEnvironment.getApplication()
        context.deleteDatabase("fca.db")
        LocalStore(context).use { store ->
            assertEquals("home_cache_missing", store.homeCheck("owner").reason)
            store.saveHome("owner", 32.0, 34.0)
            val saved = store.readableDatabase.rawQuery("SELECT saved FROM return_home", null).use {
                it.moveToFirst(); it.getLong(0)
            }
            assertEquals("home_cache_clock_invalid", store.homeCheck("owner", saved - 1).reason)
            assertNull(store.homeCheck("owner", saved + 86_400_000L).reason)
            assertEquals("home_cache_expired", store.homeCheck("owner", saved + 86_400_001L).reason)
            assertEquals(32.0 to 34.0, store.home("owner", saved))
        }
    }

    @Test fun diagnosticFailureCannotRollbackGraceReconnectOrBlockScheduling() {
        val context = RuntimeEnvironment.getApplication()
        context.deleteDatabase("fca.db")
        LocalStore(context).use { store ->
            store.installation("owner"); store.registered("owner", "00000000-0000-4000-8000-000000000001")
            store.activate("owner"); store.associate("owner", "vehicle", "local-address", 1)
            // Test database only: force the actual diagnostic writes to fail.
            store.writableDatabase.execSQL("DROP TABLE diagnostics")
            var kicks = 0; var returns = 0
            DetectorEvents.record(store, 1, true, { kicks++ }, { returns++ })
            val take = store.next("owner")!!
            DetectorEvents.record(store, 1, false, { kicks++ }, { returns++ })
            val candidate = store.candidates("owner").single()
            assertEquals(1, kicks); assertEquals(1, returns)
            ReturnWorker.diagnostic({ throw IllegalStateException("sensitive") }, "return_home_check_started")
            assertTrue(store.queueReturn(candidate, "{}", candidate.due, candidate.elapsedDue))
            assertEquals(take, store.next("owner"))
            assertEquals(2L, store.pending("owner"))
            DetectorEvents.record(store, 1, true, { kicks++ }, { returns++ })
            store.observe(1, false, 1_000, 1_000)
            val waiting = store.candidates("owner").single()
            assertEquals(31_000L, waiting.due)
            assertFalse(ReturnWorker.graceElapsed(waiting, 30_999, 31_000))
            assertFalse(ReturnWorker.graceElapsed(waiting, 31_000, 30_999))
            assertTrue(ReturnWorker.graceElapsed(waiting, 31_000, 31_000))
            assertTrue(store.observe(1, true, 30_999, 30_999))
            assertTrue(store.candidates("owner").isEmpty())
        }
    }
}

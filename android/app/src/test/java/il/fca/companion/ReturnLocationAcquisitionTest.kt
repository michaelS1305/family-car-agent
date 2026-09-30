package il.fca.companion

import android.app.Application
import android.location.Location
import android.os.CancellationSignal
import il.fca.companion.detector.ReturnLocationAcquisition
import il.fca.companion.detector.ReturnLocationAcquisition.Source
import il.fca.companion.detector.ReturnWorker
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35, 36], application = Application::class)
class ReturnLocationAcquisitionTest {
    private val now = 100_000L
    private fun fix(age: Long = 0, accuracy: Float = 10f, latitude: Double = 32.0) = Location("test").apply {
        this.latitude = latitude; longitude = 34.0; this.accuracy = accuracy
        time = now - age; elapsedRealtimeNanos = (now - age) * 1_000_000
    }
    private class Fake : ReturnLocationAcquisition.Providers {
        val unavailable = mutableSetOf<Source>()
        val disabled = mutableSetOf<Source>()
        val cache = mutableMapOf<Source, Location>()
        val callbacks = mutableMapOf<Source, (Location?) -> Unit>()
        val signals = mutableMapOf<Source, CancellationSignal>()
        var onRequest: (Source) -> Unit = {}
        var onCache: () -> Unit = {}
        override fun available(source: Source) = source !in unavailable
        override fun enabled(source: Source) = source !in disabled
        override fun cached(source: Source): Location? { onCache(); return cache[source] }
        override fun request(source: Source, cancellation: CancellationSignal, started: () -> Unit,
                             callback: (Location?) -> Unit) {
            started()
            callbacks[source] = callback; signals[source] = cancellation; onRequest(source)
        }
    }
    private fun operation(fake: Fake, logs: MutableList<String> = mutableListOf(),
                          clock: () -> Long = { now },
                          wait: (CountDownLatch, Long) -> Boolean = { _, _ -> false }) =
        ReturnLocationAcquisition(fake, { logs.add(it) }, clock, { now }, { now * 1_000_000 }, wait)

    @Test fun eachProviderCacheCanWinWithoutRequestAndPreservesTimestamps() {
        for (source in Source.entries) {
            val fake = Fake(); val cached = fix(5_000); fake.cache[source] = cached
            val logs = mutableListOf<String>()
            val result = operation(fake, logs).acquire(true, true)
            assertEquals(cached.time, result.fix!!.time)
            assertEquals(cached.elapsedRealtimeNanos, result.fix.elapsedRealtimeNanos)
            assertTrue(fake.callbacks.isEmpty())
            assertTrue(logs.contains("return_location_source_cache_${source.tag}"))
        }
    }

    @Test fun cacheUsesNewestThenAccuracyNeverHomeDistance() {
        val fake = Fake()
        fake.cache[Source.GPS] = fix(2_000, 1f)
        fake.cache[Source.NETWORK] = fix(1_000, 90f, 33.0)
        val selected = operation(fake).acquire(true, true).fix!!
        assertEquals(33.0, selected.latitude, 0.0)
        assertEquals("outside_home_radius", ReturnWorker.homeRadiusFailure(selected, 32.0 to 34.0))
        assertTrue(fake.callbacks.isEmpty())
        fake.cache[Source.GPS] = fix(1_000, 5f)
        assertEquals(5f, operation(fake).acquire(true, true).fix!!.accuracy)
    }

    @Test fun invalidCachesFallThroughToCurrentRace() {
        for (invalid in listOf(fix(30_001), fix(accuracy = 101f), fix().apply { isMock = true },
                fix().apply { latitude = Double.NaN })) {
            val fake = Fake(); fake.cache[Source.GPS] = invalid; fake.cache[Source.NETWORK] = invalid
            val result = operation(fake, wait = { _, _ ->
                assertEquals(2, fake.callbacks.size)
                fake.callbacks.getValue(Source.NETWORK)(fix()); true
            }).acquire(true, true)
            assertNotNull(result.fix)
        }
    }

    @Test fun eitherProviderWinsAndCancelsBothAndIgnoresLateCallback() {
        for (winner in Source.entries) {
            val fake = Fake(); val logs = mutableListOf<String>()
            val result = operation(fake, logs, wait = { _, _ ->
                assertEquals(2, fake.callbacks.size)
                fake.callbacks.getValue(winner)(fix(latitude = 33.0))
                assertTrue(fake.signals.values.all { it.isCanceled })
                true
            }).acquire(true, true)
            val before = logs.toList()
            fake.callbacks.values.forEach { it(fix()) }
            assertEquals(Source.entries.map { "return_location_${it.tag}_callback_late_ignored" }, logs.drop(before.size))
            assertEquals(33.0, result.fix!!.latitude, 0.0)
            assertEquals("outside_home_radius", ReturnWorker.homeRadiusFailure(result.fix, 32.0 to 34.0))
            assertEquals(1, logs.count { it.startsWith("return_location_source_current_") })
        }
    }

    @Test fun invalidProviderDoesNotTerminateOtherProvider() {
        for (invalid in Source.entries) {
            val fake = Fake()
            val other = Source.entries.first { it != invalid }
            val result = operation(fake, wait = { latch, _ ->
                fake.callbacks.getValue(invalid)(fix(accuracy = 101f))
                assertEquals(1L, latch.count)
                assertFalse(fake.signals.getValue(other).isCanceled)
                fake.callbacks.getValue(other)(fix()); true
            }).acquire(true, true)
            assertNotNull(result.fix)
        }
    }

    @Test fun providerAvailabilityAndAllUnsuccessfulFailClosedWithoutWaiting() {
        for (unavailable in Source.entries) {
            val fake = Fake(); fake.unavailable.add(unavailable)
            fake.onRequest = { fake.callbacks.getValue(it)(fix()) }
            assertNotNull(operation(fake).acquire(true, true).fix)
            assertEquals(1, fake.callbacks.size)
        }
        val fake = Fake(); fake.unavailable.add(Source.GPS); fake.disabled.add(Source.NETWORK)
        val logs = mutableListOf<String>()
        assertEquals("location_unavailable", operation(fake, logs).acquire(true, true).reason)
        assertTrue(logs.contains("return_location_gps_unavailable"))
        assertTrue(logs.contains("return_location_network_disabled"))
        val empty = Fake(); empty.onRequest = { empty.callbacks.getValue(it)(null) }
        assertEquals("location_unavailable", operation(empty, wait = { _, _ ->
            fail("Both providers completed; must not wait"); false
        }).acquire(true, true).reason)
    }

    @Test fun sharedBudgetIncludesCacheAndRequestSetupAndLateTimeoutCallbackIsIgnored() {
        var clock = now
        val fake = Fake(); fake.onCache = { clock += 2_000 }
        fake.onRequest = { clock += 1_000 }
        val logs = mutableListOf<String>()
        val result = operation(fake, logs, { clock }, { _, remaining ->
            assertEquals(14_000L, remaining)
            clock += remaining; false
        }).acquire(true, true)
        assertEquals(now + 20_000, clock)
        assertEquals("location_timeout", result.reason)
        assertTrue(fake.signals.values.all { it.isCanceled })
        val before = logs.toList()
        fake.callbacks.values.forEach { it(fix()) }
        assertEquals(Source.entries.map { "return_location_${it.tag}_callback_late_ignored" }, logs.drop(before.size))
    }

    @Test fun permissionExceptionsInterruptionAndStopRetainBoundedReasons() {
        val fake = Fake()
        assertEquals("fine_permission_missing", operation(fake).acquire(false, true).reason)
        assertEquals("background_permission_missing", operation(fake).acquire(true, false).reason)
        assertTrue(fake.callbacks.isEmpty())
        for ((exception, reason) in listOf(SecurityException("private") to "location_security_error",
                IllegalStateException("private") to "location_request_error",
                InterruptedException("private") to "location_interrupted")) {
            val broken = Fake(); broken.onRequest = { throw exception }
            val logs = mutableListOf<String>()
            assertEquals(reason, operation(broken, logs).acquire(true, true).reason)
            assertTrue(broken.signals.values.all { it.isCanceled })
            assertFalse(logs.joinToString().contains("private"))
        }
        lateinit var stopped: ReturnLocationAcquisition
        val pending = Fake()
        stopped = operation(pending, wait = { _, _ -> stopped.stop(); true })
        assertEquals("location_worker_stopped", stopped.acquire(true, true).reason)
        assertTrue(pending.signals.values.all { it.isCanceled })
        val interrupted = Fake()
        assertEquals("location_interrupted", operation(interrupted, wait = { _, _ ->
            throw InterruptedException()
        }).acquire(true, true).reason)
    }

    @Test fun simultaneousCallbacksOnlySelectOneOutcomeAndDiagnosticsMayThrow() {
        val fake = Fake(); val executor = Executors.newFixedThreadPool(2)
        try {
            val op = ReturnLocationAcquisition(fake, { throw IllegalStateException("private") },
                { now }, { now }, { now * 1_000_000 }, { latch, _ ->
                    val start = CountDownLatch(1)
                    val futures = Source.entries.map { source -> executor.submit {
                        start.await(); fake.callbacks.getValue(source)(fix())
                    } }
                    start.countDown()
                    futures.forEach { it.get(2, TimeUnit.SECONDS) }
                    assertEquals(0L, latch.count); true
                })
            assertNotNull(op.acquire(true, true).fix)
            assertTrue(fake.signals.values.all { it.isCanceled })
        } finally { executor.shutdownNow() }
    }

    @Test fun requestErrorDoesNotBlockOtherSourceAndCancellationCallbackCannotReplaceWinner() {
        val fake = Fake()
        fake.onRequest = { source -> if (source == Source.GPS) throw SecurityException("private") }
        val result = operation(fake, wait = { _, _ ->
            fake.signals.getValue(Source.NETWORK).setOnCancelListener {
                fake.callbacks.getValue(Source.NETWORK)(fix(latitude = 33.0))
            }
            fake.callbacks.getValue(Source.NETWORK)(fix()); true
        }).acquire(true, true)
        assertEquals(32.0, result.fix!!.latitude, 0.0)
        assertTrue(fake.signals.values.all { it.isCanceled })
    }

    @Test fun expiredBudgetOrStoppedOperationNeverAcceptsCacheOrCallback() {
        var clock = now
        val cache = Fake(); cache.cache[Source.GPS] = fix()
        cache.onCache = { clock += 20_000 }
        assertEquals("location_timeout", operation(cache, clock = { clock }).acquire(true, true).reason)
        assertTrue(cache.callbacks.isEmpty())
        val pending = Fake(); clock = now
        val late = operation(pending, clock = { clock }, wait = { _, _ ->
            clock = now + 20_000
            pending.callbacks.getValue(Source.GPS)(fix()); true
        }).acquire(true, true)
        assertEquals("location_timeout", late.reason)
        val stopped = operation(cache)
        stopped.stop()
        assertEquals("location_worker_stopped", stopped.acquire(true, true).reason)
    }

    @Test fun registrationDiagnosticsBracketEachCallAndFailuresAreBounded() {
        val fake = Fake(); val logs = mutableListOf<String>()
        fake.onRequest = { source ->
            assertEquals("return_location_${source.tag}_request_started", logs.last())
            assertFalse(logs.contains("return_location_${source.tag}_request_submitted"))
        }
        assertEquals("location_timeout", operation(fake, logs).acquire(true, true).reason)
        for (source in Source.entries) {
            assertTrue(logs.contains("return_location_${source.tag}_request_submitted"))
            assertTrue(logs.contains("return_location_${source.tag}_cancel_requested"))
            assertTrue(logs.contains("return_location_${source.tag}_cancel_completed"))
        }
        assertEquals(1, logs.count { it == "return_location_shared_timeout" })
        for ((error, category) in listOf(SecurityException("secret") to "security",
                IllegalStateException("secret") to "runtime", Exception("secret") to "other")) {
            val broken = Fake(); val failures = mutableListOf<String>()
            broken.onRequest = { throw error }
            assertNull(operation(broken, failures).acquire(true, true).fix)
            for (source in Source.entries) {
                assertTrue(failures.contains("return_location_${source.tag}_request_failed_$category"))
                assertFalse(failures.contains("return_location_${source.tag}_request_submitted"))
            }
            assertFalse(failures.any { it.contains("secret") || it.contains("callback_") })
        }
    }

    @Test fun callbackClassificationAndCancellationFailureDoNotChangeResults() {
        for ((value, classification) in listOf(null to "null", fix(accuracy = 101f) to
                "invalid_location_accuracy_too_low", fix() to "usable")) {
            val fake = Fake(); val logs = mutableListOf<String>()
            val result = operation(fake, logs, wait = { _, _ ->
                fake.signals.getValue(Source.GPS).setOnCancelListener { throw IllegalStateException("secret") }
                fake.callbacks.getValue(Source.GPS)(value)
                fake.callbacks.getValue(Source.NETWORK)(fix())
                true
            }).acquire(true, true)
            assertNotNull(result.fix)
            assertTrue(logs.contains("return_location_gps_callback_$classification"))
            assertTrue(logs.contains("return_location_gps_cancel_failed"))
            assertTrue(logs.contains("return_location_network_cancel_completed"))
            assertFalse(logs.any { it.contains("secret") })
        }
    }
}

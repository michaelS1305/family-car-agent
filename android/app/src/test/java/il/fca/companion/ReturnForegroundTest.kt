package il.fca.companion

import android.app.Application
import android.content.ComponentName
import android.content.pm.ServiceInfo
import android.location.Location
import android.os.SystemClock
import il.fca.companion.data.Association
import il.fca.companion.data.LocalStore
import il.fca.companion.data.ReturnCandidate
import il.fca.companion.detector.ReturnController
import il.fca.companion.detector.ReturnExecution
import il.fca.companion.detector.ReturnForegroundService
import il.fca.companion.detector.ReturnWorker
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35, 36], application = Application::class)
class ReturnForegroundTest {
    private val context get() = RuntimeEnvironment.getApplication()
    private fun store(): LocalStore {
        context.deleteDatabase("fca.db")
        return LocalStore(context).apply {
            installation("owner"); registered("owner", "00000000-0000-4000-8000-000000000001")
            activate("owner"); associate("owner", "vehicle", "AA:BB:CC:DD:EE:FF", 7)
        }
    }
    private class Timer(val at: Long, val action: () -> Unit) { var cancelled = false }
    private inner class Harness(val store: LocalStore) : ReturnController.Ports {
        var now = 100_000L
        var elapsedNow = 100_000L
        var invalidReason: String? = null
        var writesFail = false
        var acquisitions = 0
        var cancels = 0
        var decisions = 0
        var wakeHeld = false
        var wakeDeadline = 0L
        var idleCount = 0
        val logs = mutableListOf<String>()
        val callbacks = mutableListOf<(ReturnWorker.LocationCheck) -> Unit>()
        val timers = mutableListOf<Timer>()
        var controller = ReturnController(this)
        fun disconnect(): ReturnCandidate {
            store.observe(7, true, now, elapsedNow)
            store.observe(7, false, now, elapsedNow)
            return store.candidates("owner").single()
        }
        fun advance(delta: Long) {
            val end = elapsedNow + delta
            while (true) {
                val timer = timers.filter { !it.cancelled && it.at <= end }.minByOrNull { it.at } ?: break
                timer.cancelled = true
                now += timer.at - elapsedNow; elapsedNow = timer.at
                timer.action()
            }
            now += end - elapsedNow; elapsedNow = end
        }
        override fun candidates() = store.activeOwner()?.let(store::candidates).orEmpty()
        override fun invalid(candidate: ReturnCandidate): String? = invalidReason ?: if (
            store.activeOwner() != candidate.owner || candidate !in candidates() ||
            store.associations(candidate.owner).none { it.vehicle == candidate.vehicle && !it.connected }
        ) "candidate_invalid" else null
        override fun wall() = now
        override fun elapsed() = elapsedNow
        override fun later(delay: Long, action: () -> Unit): ReturnController.Cancel {
            val timer = Timer(elapsedNow + delay, action); timers.add(timer)
            return ReturnController.Cancel { timer.cancelled = true }
        }
        override fun acquire(candidate: ReturnCandidate, complete: (ReturnWorker.LocationCheck) -> Unit): ReturnController.Cancel {
            acquisitions++; callbacks.add(complete)
            return ReturnController.Cancel { cancels++ }
        }
        override fun decide(candidate: ReturnCandidate, result: ReturnWorker.LocationCheck): String {
            decisions++
            if (result.reason != null) return result.reason
            return if (store.queueReturn(candidate, "{}", now, elapsedNow)) "queued" else "candidate_invalid"
        }
        override fun abandon(candidate: ReturnCandidate) = store.abandon(candidate)
        override fun awake(remaining: Long) { assertFalse(wakeHeld); wakeHeld = true; wakeDeadline = elapsedNow + remaining }
        override fun release() { wakeHeld = false }
        override fun idle() { idleCount++ }
        override fun diagnostic(message: String) { if (writesFail) error("private"); logs.add(message) }
    }

    @Test fun associationRequiresBothSystemIdAndMac() {
        val local = Association("vehicle", "AA:BB:CC:DD:EE:FF", 7, false)
        assertTrue(ReturnExecution.matches(local, listOf(7 to "aa:bb:cc:dd:ee:ff")))
        assertFalse(ReturnExecution.matches(local, emptyList()))
        assertFalse(ReturnExecution.matches(local, listOf(8 to local.address)))
        assertFalse(ReturnExecution.matches(local, listOf(7 to "AA:BB:CC:DD:EE:00")))
        assertFalse(ReturnExecution.matches(local, listOf(7 to null)))
    }

    @Test fun delayedStartAndDuplicatesUseOriginalGraceAndWatchdog() = store().use { store ->
        val h = Harness(store); val candidate = h.disconnect()
        h.advance(8_000); h.controller.refresh()
        assertEquals(22_000, ReturnController.remainingGrace(candidate, h.now, h.elapsedNow))
        assertEquals(160_000L, h.wakeDeadline)
        repeat(4) { h.controller.refresh() } // detector + one-time + periodic requests
        h.advance(21_999); assertEquals(0, h.acquisitions)
        h.advance(1); assertEquals(1, h.acquisitions)
        repeat(4) { h.controller.refresh() }
        assertEquals(1, h.acquisitions)
        assertEquals(candidate, store.candidates("owner").single())
        h.controller.close(); assertFalse(h.wakeHeld)
    }

    @Test fun reconnectDuringGraceNeverAcquiresOrReturns() = store().use { store ->
        val h = Harness(store); h.disconnect(); h.controller.refresh(); h.advance(29_999)
        store.observe(7, true, h.now, h.elapsedNow); h.controller.refresh(); h.advance(60_000)
        assertEquals(0, h.acquisitions); assertEquals(0, h.decisions)
        assertEquals(2L, store.pending("owner")); assertFalse(h.wakeHeld)
    }

    @Test fun reconnectCancelsAcquisitionAndOldCompletionCannotStopNewGeneration() = store().use { store ->
        val h = Harness(store); h.disconnect(); h.controller.refresh(); h.advance(30_000)
        val old = h.callbacks.single()
        store.observe(7, true, h.now, h.elapsedNow)
        h.controller.refresh(); assertEquals(1, h.cancels); assertFalse(h.wakeHeld)
        store.observe(7, false, h.now, h.elapsedNow)
        val newer = store.candidates("owner").single(); h.controller.refresh()
        val deadline = h.wakeDeadline
        old(ReturnWorker.LocationCheck())
        assertEquals(newer, store.candidates("owner").single()); assertTrue(h.wakeHeld)
        assertEquals(deadline, h.wakeDeadline); assertEquals(0, h.decisions)
        h.advance(30_000); assertEquals(2, h.acquisitions)
        h.callbacks.last()(ReturnWorker.LocationCheck())
        assertEquals(1, h.decisions); assertFalse(h.wakeHeld)
        assertEquals(3L, store.pending("owner")) // two unchanged TAKEs, one RETURN
    }

    @Test fun timeoutOutsideInvalidPermissionAndMissingAssociationTerminate() {
        for (reason in listOf("location_timeout", "outside_home_radius", "location_accuracy_too_low")) store().use { store ->
            val h = Harness(store); h.disconnect(); h.controller.refresh(); h.advance(30_000)
            h.callbacks.single()(ReturnWorker.LocationCheck(reason = reason))
            assertFalse(h.wakeHeld); assertTrue(store.candidates("owner").isEmpty())
            assertEquals(1L, store.pending("owner")); assertTrue(h.logs.contains("return_fgs_stopped_$reason"))
        }
        for (reason in listOf("association_missing", "fine_permission_missing", "background_permission_missing", "location_disabled")) store().use { store ->
            val h = Harness(store); h.disconnect(); h.invalidReason = reason; h.controller.refresh()
            assertEquals(0, h.acquisitions); assertFalse(h.wakeHeld)
            assertTrue(store.candidates("owner").isEmpty())
        }
    }

    @Test fun watchdogDoesNotResetAndLateSuccessCannotQueue() = store().use { store ->
        val h = Harness(store); h.disconnect(); h.controller.refresh(); h.advance(30_000)
        h.advance(29_999); h.controller.refresh(); h.advance(1)
        assertTrue(h.logs.contains("return_fgs_watchdog_expired")); assertFalse(h.wakeHeld)
        assertEquals(1, h.cancels)
        h.callbacks.single()(ReturnWorker.LocationCheck())
        assertEquals(0, h.decisions); assertEquals(1L, store.pending("owner"))
    }

    @Test fun recreationPreservesGraceAndExpiredCandidateCannotRestart() = store().use { store ->
        val h = Harness(store); val candidate = h.disconnect(); h.controller.refresh(); h.advance(8_000)
        h.controller.close(); assertFalse(h.wakeHeld)
        assertEquals(candidate, store.candidates("owner").single())
        h.controller = ReturnController(h); h.controller.refresh(); h.advance(21_999)
        assertEquals(0, h.acquisitions); h.advance(1); assertEquals(1, h.acquisitions)
        h.controller.close(); h.advance(30_000)
        h.controller = ReturnController(h); h.controller.refresh()
        assertEquals(1, h.acquisitions); assertFalse(h.wakeHeld)
        assertTrue(store.candidates("owner").isEmpty())
    }

    @Test fun diagnosticFailureAndDuplicateCompletionPreserveOutboxAndSequence() = store().use { store ->
        val h = Harness(store); h.writesFail = true; h.disconnect()
        val take = store.next("owner")!!
        h.controller.refresh(); h.advance(30_000)
        repeat(2) { h.callbacks.single()(ReturnWorker.LocationCheck()) }
        assertEquals(1, h.decisions); assertFalse(h.wakeHeld)
        assertEquals(take, store.next("owner")); assertEquals(2L, store.pending("owner"))
        store.finish(take.id, "accepted")
        val returned = store.next("owner")!!
        assertEquals(take.sequence + 1, returned.sequence); assertEquals("return", returned.type)
        assertNotEquals(take.id, returned.id)
    }

    @Test fun accountInvalidationAndLateCompletionFailClosed() = store().use { store ->
        val h = Harness(store); h.disconnect(); h.controller.refresh(); h.advance(30_000)
        store.activate(null); h.controller.refresh()
        h.callbacks.single()(ReturnWorker.LocationCheck())
        assertEquals(0, h.decisions); assertFalse(h.wakeHeld); assertEquals(1, h.cancels)
    }

    @Test fun stateNotificationsAreAfterCommitAndCannotBreakTransitions() = store().use { store ->
        var notifications = 0
        val listener: () -> Unit = {
            assertFalse(store.writableDatabase.inTransaction())
            notifications++
            throw IllegalStateException("private diagnostic failure")
        }
        LocalStore.listen(listener)
        try {
            store.observe(7, true); store.observe(7, false)
            val candidate = store.candidates("owner").single()
            store.abandon(candidate)
            store.activate(null)
            assertEquals(4, notifications)
            assertEquals(1L, store.pending("owner"))
            assertTrue(store.candidates("owner").isEmpty())
        } finally { LocalStore.unlisten(listener) }
    }

    @Test fun actualQualificationQueuesExactlyOnceAndOutsideHomeNeverQueues() {
        for (latitude in listOf(32.0, 33.0)) store().use { store ->
            val now = System.currentTimeMillis(); val elapsed = SystemClock.elapsedRealtime()
            store.observe(7, true, now - 31_000, elapsed - 31_000)
            store.observe(7, false, now - 30_000, elapsed - 30_000)
            store.saveHome("owner", 32.0, 34.0)
            val candidate = store.candidates("owner").single()
            val fix = Location("gps").apply {
                this.latitude = latitude; longitude = 34.0; accuracy = 10f
                time = now; elapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos()
            }
            var deliveries = 0
            val execution = ReturnExecution(context, store) { deliveries++ }
            val result = execution.decide(candidate, ReturnWorker.LocationCheck(fix))
            assertEquals(if (latitude == 32.0) "queued" else "outside_home_radius", result)
            if (latitude == 32.0) {
                assertEquals("candidate_invalid", execution.decide(candidate, ReturnWorker.LocationCheck(fix)))
                assertEquals(1, deliveries); assertEquals(2L, store.pending("owner"))
            } else { assertEquals(0, deliveries); assertEquals(1L, store.pending("owner")) }
        }
    }

    @Test fun servicePromotesInOnCreateBeforeAnyStartOrAcquisitionAndManifestIsInternalLocation() {
        val info = context.packageManager.getServiceInfo(ComponentName(context, ReturnForegroundService::class.java), 0)
        assertFalse(info.exported)
        assertEquals(ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION, info.foregroundServiceType)
        val service = Robolectric.buildService(ReturnForegroundService::class.java).create()
        try {
            val notification = shadowOf(service.get()).lastForegroundNotification
            assertNotNull(notification)
            assertEquals("Family Car Agent", notification.extras.getCharSequence("android.title").toString())
            assertEquals("מעדכן את מצב הרכב…", notification.extras.getCharSequence("android.text").toString())
        } finally { service.destroy() }
    }
}

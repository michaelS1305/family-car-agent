package il.fca.companion

import android.app.Application
import android.content.Context
import androidx.work.*
import androidx.work.testing.WorkManagerTestInitHelper
import il.fca.companion.data.LocalStore
import il.fca.companion.delivery.DeliveryDrain
import il.fca.companion.delivery.DeliveryWorker
import il.fca.companion.delivery.DrainOutcome
import il.fca.companion.net.HttpFailure
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class DeliverySchedulingTest {
    private fun store(): LocalStore {
        val context = RuntimeEnvironment.getApplication()
        context.deleteDatabase("fca.db")
        return LocalStore(context).apply {
            installation("owner"); registered("owner", UUID.randomUUID().toString())
            activate("owner"); associate("owner", "car", "local", 1); observe(1, true)
        }
    }
    @Test fun freshKickIsIndependentOfBackoffAndNetworkConstrained() {
        val starts = mutableListOf<Pair<String?, Int>>()
        val context = RuntimeEnvironment.getApplication()
        val factory = object : WorkerFactory() {
            override fun createWorker(context: Context, name: String, params: WorkerParameters): ListenableWorker =
                object : Worker(context, params) {
                    override fun doWork(): Result {
                        starts.add(inputData.getString("source") to runAttemptCount)
                        return if (inputData.getString("source") == "recovery") Result.retry() else Result.success()
                    }
                }
        }
        WorkManagerTestInitHelper.initializeTestWorkManager(context,
            Configuration.Builder().setExecutor { it.run() }.setWorkerFactory(factory).build())
        val manager = WorkManager.getInstance(context)
        val driver = WorkManagerTestInitHelper.getTestDriver(context)!!
        val recovery = DeliveryWorker.recoveryRequest()
        manager.enqueueUniqueWork("fca-delivery-recovery", ExistingWorkPolicy.APPEND_OR_REPLACE, recovery).result.get()
        driver.setInitialDelayMet(recovery.id)
        driver.setAllConstraintsMet(recovery.id)
        assertEquals(listOf("recovery" to 0), starts)
        assertEquals(WorkInfo.State.ENQUEUED, manager.getWorkInfoById(recovery.id).get()!!.state)

        // Exercise production enqueue, not a test-only replacement policy.
        DeliveryWorker.enqueue(context)
        val kick = manager.getWorkInfosByTag(DeliveryWorker::class.java.name).get().single { it.id != recovery.id }
        assertEquals(0, kick.runAttemptCount)
        assertEquals(WorkInfo.State.ENQUEUED, kick.state)
        assertEquals(1, starts.size) // network constraint has not been satisfied
        driver.setAllConstraintsMet(kick.id)
        assertEquals("kick" to 0, starts.last())
        assertEquals(WorkInfo.State.SUCCEEDED, manager.getWorkInfoById(kick.id).get()!!.state)
        assertEquals(WorkInfo.State.ENQUEUED, manager.getWorkInfoById(recovery.id).get()!!.state)
        WorkManagerTestInitHelper.closeWorkDatabase()
    }
    @Test fun expeditedKickHasFallbackAndNoDelayOrDependencies() {
        val first = DeliveryWorker.kickRequest()
        val second = DeliveryWorker.kickRequest()
        assertNotEquals(first.id, second.id)
        assertTrue(first.workSpec.expedited)
        assertEquals(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST, first.workSpec.outOfQuotaPolicy)
        assertEquals(NetworkType.CONNECTED, first.workSpec.constraints.requiredNetworkType)
        assertEquals(0L, first.workSpec.initialDelay)
        assertEquals(0, first.workSpec.runAttemptCount)
    }
    @Test fun concurrentDrainsSerializeAcrossHttpAndAcknowledgeOnlyOnce() {
        val store = store()
        val entered = CountDownLatch(1); val release = CountDownLatch(1)
        val calls = AtomicInteger()
        val executor = Executors.newFixedThreadPool(2)
        try {
            val first = executor.submit<DrainOutcome> {
                DeliveryDrain.run(store, { "owner" }, { false }) { _, _, _ ->
                    calls.incrementAndGet(); entered.countDown()
                    check(release.await(5, TimeUnit.SECONDS)); "{\"kind\":\"accepted\"}"
                }
            }
            assertTrue(entered.await(5, TimeUnit.SECONDS))
            val second = executor.submit<DrainOutcome> {
                DeliveryDrain.run(store, { "owner" }, { false }) { _, _, _ ->
                    calls.incrementAndGet(); "{\"kind\":\"accepted\"}"
                }
            }
            release.countDown()
            assertEquals(DrainOutcome.COMPLETE, first.get(5, TimeUnit.SECONDS))
            assertEquals(DrainOutcome.COMPLETE, second.get(5, TimeUnit.SECONDS))
            assertEquals(1, calls.get()); assertEquals(0L, store.pending("owner"))
        } finally { release.countDown(); executor.shutdownNow(); store.close() }
    }
    @Test fun failureRetainsExactHeadAndTakePrecedesReturnOnRetry() {
        val store = store()
        val take = store.next("owner")!!
        store.observe(1, false, 1_000, 1_000)
        val candidate = store.candidates("owner").single()
        store.queueReturn(candidate, "{\"take_event_id\":\"${take.id}\"}", 61_000, 61_000)
        var failedPayload = ""
        assertEquals(DrainOutcome.RECOVER, DeliveryDrain.run(store, { "owner" }, { false }) { _, _, body ->
            failedPayload = body.toString(); throw HttpFailure(503)
        })
        assertEquals(take, store.next("owner")); assertEquals(2L, store.pending("owner"))
        val types = mutableListOf<String>()
        assertEquals(DrainOutcome.COMPLETE, DeliveryDrain.run(store, { "owner" }, { false }) { _, path, body ->
            if (types.isEmpty()) assertEquals(failedPayload, body.toString())
            types.add(path.substringAfterLast('/')); "{\"kind\":\"accepted\"}"
        })
        assertEquals(listOf("take", "return"), types)
        assertEquals(0L, store.pending("owner")); store.close()
    }
    @Test fun eventPersistedAtDrainBoundaryHasAnotherIndependentOpportunity() {
        val store = store()
        DeliveryDrain.run(store, { "owner" }, { false }) { _, _, _ -> "{\"kind\":\"accepted\"}" }
        // Worst boundary: previous drain already observed empty and exited.
        store.observe(1, false); store.observe(1, true)
        val event = store.next("owner")!!
        assertEquals(0, DeliveryWorker.kickRequest().workSpec.runAttemptCount)
        DeliveryDrain.run(store, { "owner" }, { false }) { _, _, body ->
            assertEquals(event.id, body.getString("event_id")); "{\"kind\":\"accepted\"}"
        }
        assertEquals(0L, store.pending("owner")); store.close()
    }
    @Test fun eventPersistedDuringHttpIsDrainedWithoutLosingItsWakeup() {
        val store = store(); val calls = AtomicInteger()
        val writer = Executors.newSingleThreadExecutor()
        try {
            assertEquals(DrainOutcome.COMPLETE, DeliveryDrain.run(store, { "owner" }, { false }) { _, _, _ ->
                if (calls.incrementAndGet() == 1) {
                    // A detector can commit while HTTP is in flight: the drain
                    // mutex must not be a SQLite transaction or detector lock.
                    writer.submit { store.observe(1, false); store.observe(1, true) }.get(5, TimeUnit.SECONDS)
                }
                "{\"kind\":\"accepted\"}"
            })
            assertEquals(2, calls.get()); assertEquals(0L, store.pending("owner"))
        } finally { writer.shutdownNow(); store.close() }
    }
    @Test fun diagnosticStorageFailureCannotChangeDrainOrRetryOutcome() = store().use { store ->
        val head = store.next("owner")!!
        // Isolated test DB: fail real diagnostic writes, not outbox persistence.
        store.writableDatabase.execSQL("DROP TABLE diagnostics")
        for (failure in listOf(HttpFailure(404, "DEVICE_OR_VEHICLE_UNAVAILABLE"),
                IllegalStateException("private transport failure"))) {
            assertEquals(DrainOutcome.RECOVER, DeliveryDrain.run(store, { "owner" }, { false }) { _, _, _ ->
                throw failure
            })
            assertEquals(head, store.next("owner"))
        }
        assertEquals(DrainOutcome.RECOVER, DeliveryDrain.run(store, { "owner" }, { false }) { _, _, _ ->
            "{\"kind\":\"conflict\"}"
        })
        assertEquals(head, store.next("owner"))
        assertEquals(DrainOutcome.COMPLETE, DeliveryDrain.run(store, { "owner" }, { false }) { _, _, body ->
            assertEquals(head.id, body.getString("event_id"))
            assertEquals(head.sequence, body.getLong("device_sequence"))
            "{\"kind\":\"accepted\"}"
        })
        assertEquals(0L, store.pending("owner"))
    }
    @Test fun stoppedOrWrongAccountDoesNotSendOrMutateQueue() {
        val store = store(); val original = store.next("owner")
        for (stopped in listOf(true, false)) {
            assertEquals(DrainOutcome.RECOVER, DeliveryDrain.run(store, { "other" }, { stopped }) { _, _, _ ->
                fail("Must not send"); ""
            })
            assertEquals(original, store.next("owner"))
        }
        store.close()
    }
}

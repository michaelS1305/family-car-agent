package il.fca.companion

import android.app.Application
import il.fca.companion.data.LocalStore
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class CompanionAccountRefreshTest {
    private lateinit var store: LocalStore
    private val device = "00000000-0000-4000-8000-000000000001"
    private var auth: String? = "owner"
    @Before fun setup() {
        val app = RuntimeEnvironment.getApplication()
        app.deleteDatabase("fca.db")
        store = LocalStore(app)
        store.activate("owner"); store.installation("owner"); store.registered("owner", device)
        store.associate("owner", "usable", "AA", 1)
        store.associate("owner", "unusable", "BB", 2)
    }
    @After fun close() { store.close() }
    private fun response(path: String): String = when (path) {
        "/api/devices" -> """[{"device_ref":"$device","revoked_at":null}]"""
        "/api/devices/$device/vehicle-bindings" -> """[{"vehicle_ref":"usable","usable":true}]"""
        "/api/devices/$device/return-home" -> """{"latitude":1.0,"longitude":2.0}"""
        else -> error("Unexpected API path")
    }
    @Test fun refreshPreservesUsableBindingAndCachesHome() {
        val stops = mutableListOf<Int>()
        CompanionAccountRefresh.refresh(store, "owner", { auth }, ::response, stops::add)
        assertEquals(listOf(2), stops)
        assertEquals(listOf("usable"), store.associations("owner").map { it.vehicle })
        assertEquals(1.0 to 2.0, store.home("owner"))
    }
    @Test fun homeFailureClearsCacheAndKeepsBindingRefresh() {
        store.saveHome("owner", 3.0, 4.0)
        CompanionAccountRefresh.refresh(store, "owner", { auth }, { path ->
            if (path.endsWith("return-home")) error("fixture failure") else response(path)
        }, {})
        assertNull(store.home("owner"))
        assertEquals(1, store.associations("owner").size)
        assertTrue(store.diagnostics().contains("return_home_refresh_failed"))
        assertFalse(store.diagnostics().contains("fixture failure"))
    }
    @Test fun ownerChangeDuringResponseCannotClearOrOverwriteNewHome() {
        CompanionAccountRefresh.refresh(store, "owner", { auth }, { path ->
            if (path.endsWith("return-home")) {
                store.activate("new-owner"); auth = "new-owner"
                store.saveHome("new-owner", 3.0, 4.0)
                error("stale failure")
            }
            response(path)
        }, {})
        assertEquals(3.0 to 4.0, store.home("new-owner"))
        assertNull(store.home("owner"))
        assertFalse(store.diagnostics().contains("return_home_refresh_failed"))
    }
    @Test fun staleSuccessAndSwitchBackAreDiscarded() {
        CompanionAccountRefresh.refresh(store, "owner", { auth }, { path ->
            if (path.endsWith("return-home")) {
                store.activate(null); store.activate("owner")
            }
            response(path)
        }, {})
        assertNull(store.home("owner"))
    }
    @Test fun wrongAuthenticatedOwnerDoesNoWork() {
        CompanionAccountRefresh.refresh(store, "owner", { "other" }, { error("Must not call API") }, { error("Must not stop") })
        assertEquals(2, store.associations("owner").size)
    }
    @Test fun bindingFailurePropagatesWithoutClearingHome() {
        store.saveHome("owner", 3.0, 4.0)
        assertThrows(IllegalStateException::class.java) {
            CompanionAccountRefresh.refresh(store, "owner", { auth }, { path ->
                if (path.endsWith("vehicle-bindings")) error("binding failure") else response(path)
            }, {})
        }
        assertEquals(3.0 to 4.0, store.home("owner"))
    }
    @Test fun stopFailureStillLeavesRemovalAppliedAsBefore() {
        assertThrows(IllegalStateException::class.java) {
            CompanionAccountRefresh.refresh(store, "owner", { auth }, ::response, { error("stop failure") })
        }
        assertEquals(listOf("usable"), store.associations("owner").map { it.vehicle })
    }
    @Test fun overlappingCallsShareOneRefresh() {
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val joining = CountDownLatch(1)
        val calls = AtomicInteger()
        val pool = Executors.newFixedThreadPool(2)
        try {
            val first = pool.submit {
                CompanionAccountRefresh.refresh(store, "owner", { auth }, { path ->
                    calls.incrementAndGet()
                    if (path == "/api/devices") { entered.countDown(); check(release.await(10, TimeUnit.SECONDS)) }
                    response(path)
                }, {})
            }
            assertTrue(entered.await(10, TimeUnit.SECONDS))
            val second = pool.submit {
                joining.countDown()
                CompanionAccountRefresh.refresh(store, "owner", { auth }, { error("Duplicate request") }, {})
            }
            assertTrue(joining.await(10, TimeUnit.SECONDS))
            // The second call must wait for the shared result, not return a fabricated success.
            assertThrows(java.util.concurrent.TimeoutException::class.java) { second.get(100, TimeUnit.MILLISECONDS) }
            release.countDown()
            first.get(10, TimeUnit.SECONDS); second.get(10, TimeUnit.SECONDS)
            assertEquals(3, calls.get())
        } finally { release.countDown(); pool.shutdownNow() }
    }
}

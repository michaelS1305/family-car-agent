package il.fca.companion

import android.app.Application
import il.fca.companion.data.LocalStore
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class LocalStoreTest {
    private fun setup(): LocalStore {
        val context = RuntimeEnvironment.getApplication()
        context.deleteDatabase("fca.db")
        return LocalStore(context).apply {
            installation("mother"); registered("mother", UUID.randomUUID().toString())
            activate("mother"); associate("mother", "Hyundai", "address-one", 1)
        }
    }
    @Test fun duplicateConnectAndDisconnectDoNotCreateExtraTake() {
        val store = setup()
        assertTrue(store.observe(1, true))
        val first = store.next("mother")!!
        assertFalse(store.observe(1, true))
        assertEquals(first, store.next("mother"))
        assertFalse(store.observe(1, false))
        assertEquals(1L, store.pending("mother"))
        assertTrue(store.observe(1, true))
        assertEquals(2L, store.pending("mother"))
    }
    @Test fun processReopenPreservesIdentitySequenceAndPendingPayload() {
        val store = setup(); store.observe(1, true)
        val first = store.next("mother")!!; store.close()
        val reopened = LocalStore(RuntimeEnvironment.getApplication())
        assertEquals(first, reopened.next("mother"))
        assertEquals(2L, reopened.installation("mother").next)
        assertFalse(reopened.observe(1, true))
        reopened.finish(first.id, "retry")
        assertNull(reopened.next("mother"))
    }
    @Test fun multipleVehiclesAndDifferentAccountIsolation() {
        val store = setup()
        store.associate("mother", "Toyota", "address-two", 2)
        assertTrue(store.observe(1, true)); assertTrue(store.observe(2, true))
        store.activate("other")
        assertFalse(store.observe(1, true))
        assertNull(store.next("other")); assertEquals(2L, store.pending("mother"))
    }
    @Test fun ambiguousBluetoothCannotMapToTwoVehicles() {
        val store = setup()
        assertThrows(android.database.sqlite.SQLiteConstraintException::class.java) {
            store.associate("mother", "Toyota", "address-one", 2)
        }
        assertEquals(1, store.associations("mother").size)
        assertFalse(store.observe(999, true))
    }
    @Test fun rebootRearmsButDoesNotErasePendingOrResetSequence() {
        val store = setup()
        store.observeBoot(1); store.observe(1, true)
        val first = store.next("mother")!!
        store.observeBoot(1)
        assertFalse(store.observe(1, true))
        store.observeBoot(2)
        assertTrue(store.observe(1, true))
        assertEquals(first, store.next("mother"))
        assertEquals(3L, store.installation("mother").next)
    }
}

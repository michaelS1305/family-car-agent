package il.fca.companion

import il.fca.companion.net.*
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.*
import org.junit.Assert.*
import org.junit.Test
import java.util.Base64
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicReference

class RealtimeBroadcastTest {
    private val token = "fixture." + Base64.getUrlEncoder().withoutPadding()
        .encodeToString("{\"exp\":3600}".toByteArray()) + ".fixture"

    private class Transport : BroadcastTransport {
        val events = Channel<BroadcastSignal>(Channel.UNLIMITED)
        override val signals = events.receiveAsFlow()
        val joined = CompletableDeferred<Unit>()
        val disposed = CompletableDeferred<Unit>()
        val updated = CompletableDeferred<String>()
        override suspend fun subscribe() { joined.complete(Unit) }
        override suspend fun updateAuth(token: String) { updated.complete(token) }
        override suspend fun dispose() { disposed.complete(Unit); events.close() }
    }

    @Test fun passesExactChannelAndEventUsesExistingOwnerAndDisposes() = runBlocking {
        val transport = Transport()
        val seen = CopyOnWriteArrayList<BroadcastSignal>()
        val adapter = RealtimeBroadcast({ "owner" }, { owner ->
            assertEquals("owner", owner); token
        }, { channel, event, _ ->
            assertEquals("family:42:car-status", channel)
            assertEquals("car_status_changed", event)
            transport
        }, { 0L })
        val job = launch { adapter.subscribe("owner", "family:42:car-status", "car_status_changed").collect { seen += it } }
        withTimeout(2_000) {
            transport.joined.await()
            assertEquals(token, transport.updated.await())
            transport.events.send(BroadcastSignal.INVALIDATED)
            while (BroadcastSignal.INVALIDATED !in seen) yield()
        }
        job.cancelAndJoin()
        assertTrue(transport.disposed.isCompleted)
        assertFalse(seen.toString().contains(token))
    }

    @Test fun staleOwnerFailsClosedAndDisposes() = runBlocking {
        val owner = AtomicReference("first")
        val transport = Transport()
        val seen = CopyOnWriteArrayList<BroadcastSignal>()
        val adapter = RealtimeBroadcast({ owner.get() }, { token }, { _, _, _ -> transport }, { 0L })
        val job = launch { adapter.subscribe("first", "family:1:car-status", "car_status_changed").collect { seen += it } }
        withTimeout(2_000) {
            transport.updated.await()
            owner.set("second")
            transport.events.send(BroadcastSignal.INVALIDATED)
            job.join()
        }
        assertEquals(listOf(BroadcastSignal.ERROR), seen.toList())
        assertTrue(transport.disposed.isCompleted)
    }

    @Test fun rawTokenErrorDoesNotEscape() = runBlocking {
        val transport = Transport()
        val adapter = RealtimeBroadcast({ "owner" }, { error(token) }, { _, _, _ -> transport })
        val result = withTimeout(2_000) { adapter.subscribe("owner", "channel", "event").toList() }
        assertEquals(listOf(BroadcastSignal.ERROR), result)
        assertTrue(transport.disposed.isCompleted)
        assertFalse(result.toString().contains(token))
    }

    @Test fun expiryTimerIsNotPeriodicStatePolling() {
        assertEquals(3_570_000L, RealtimeBroadcast.refreshDelay(token, 0))
        assertThrows(IllegalStateException::class.java) { RealtimeBroadcast.refreshDelay(token, 3_580_000) }
    }
}

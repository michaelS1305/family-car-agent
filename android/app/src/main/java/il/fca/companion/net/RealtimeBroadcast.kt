package il.fca.companion.net

import il.fca.companion.BuildConfig
import il.fca.companion.auth.SessionStore
import io.github.jan.supabase.createSupabaseClient
import io.github.jan.supabase.logging.LogLevel
import io.github.jan.supabase.realtime.*
import io.ktor.client.engine.okhttp.OkHttp
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import java.util.Base64

/** No payloads, credentials, identifiers or raw errors escape this boundary. */
internal enum class BroadcastSignal { CONNECTING, SUBSCRIBED, DISCONNECTED, INVALIDATED, ERROR }

internal interface BroadcastTransport {
    val signals: Flow<BroadcastSignal>
    suspend fun subscribe()
    suspend fun updateAuth(token: String)
    suspend fun dispose()
}

/** Cold, owner-bound subscription. Cancel collection to unsubscribe and release the socket.
 * Not wired to any screen yet. The caller must cancel on logout/family change.
 */
internal class RealtimeBroadcast internal constructor(
    private val currentOwner: () -> String?,
    private val access: suspend (String) -> String,
    private val factory: (String, String, suspend () -> String) -> BroadcastTransport,
    private val now: () -> Long = System::currentTimeMillis,
) {
    constructor(auth: SessionStore) : this(auth::owner, { auth.access(it) },
        { channel, event, token -> SupabaseBroadcastTransport(channel, event, token) })

    fun subscribe(owner: String, channel: String, event: String): Flow<BroadcastSignal> = flow {
        var transport: BroadcastTransport? = null
        try {
            check(currentOwner() == owner)
            val tokenProvider: suspend () -> String = {
                check(currentOwner() == owner)
                val token = access(owner)
                check(currentOwner() == owner)
                token
            }
            transport = factory(channel, event, tokenProvider)
            val connection = transport
            emitAll(channelFlow {
                // Start listeners before joining; payloads are discarded by the transport.
                launch(start = CoroutineStart.UNDISPATCHED) {
                    connection.signals.collect { signal ->
                        check(currentOwner() == owner)
                        send(signal)
                    }
                }
                check(withTimeoutOrNull(20_000) { connection.subscribe(); true } == true)
                launch {
                    while (isActive) {
                        val token = tokenProvider()
                        val wait = refreshDelay(token, now())
                        connection.updateAuth(token)
                        // Credential-expiry timer only: no periodic API/state polling.
                        delay(wait)
                    }
                }
                awaitCancellation()
            })
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            emit(BroadcastSignal.ERROR)
        } finally {
            withContext(NonCancellable) {
                try { withTimeout(5_000) { transport?.dispose() } }
                catch (_: Exception) { /* Cleanup never exposes transport exceptions. */ }
            }
        }
    }.flowOn(Dispatchers.IO)

    companion object {
        internal fun refreshDelay(token: String, now: Long): Long {
            // Read expiry only for scheduling; Supabase remains the JWT verifier.
            val body = Base64.getUrlDecoder().decode(token.split('.')[1]).toString(Charsets.UTF_8)
            val expiry = Json.parseToJsonElement(body) as JsonObject
            val seconds = checkNotNull(expiry["exp"]?.jsonPrimitive?.longOrNull)
            val wait = Math.subtractExact(Math.multiplyExact(seconds, 1000), now) - 30_000
            check(wait > 0) // Fail closed rather than spin on a stale credential.
            return wait
        }
    }
}

private class SupabaseBroadcastTransport(
    channelName: String, event: String, token: suspend () -> String,
) : BroadcastTransport {
    private val client = createSupabaseClient(BuildConfig.SUPABASE_URL, BuildConfig.SUPABASE_PUBLISHABLE_KEY) {
        defaultLogLevel = LogLevel.NONE
        httpEngine = OkHttp.create()
        install(Realtime) {
            accessToken = { token() }
        }
    }
    private val channel = client.channel(channelName) { isPrivate = true }
    override val signals: Flow<BroadcastSignal> = merge(
        channel.broadcastFlow<JsonObject>(event).map { BroadcastSignal.INVALIDATED },
        channel.status.map {
            when (it) {
                RealtimeChannel.Status.SUBSCRIBED -> BroadcastSignal.SUBSCRIBED
                RealtimeChannel.Status.SUBSCRIBING -> BroadcastSignal.CONNECTING
                else -> BroadcastSignal.DISCONNECTED
            }
        },
        client.realtime.status.filter { it != Realtime.Status.CONNECTED }.map {
            if (it == Realtime.Status.CONNECTING) BroadcastSignal.CONNECTING else BroadcastSignal.DISCONNECTED
        },
    )
    override suspend fun subscribe() = channel.subscribe(blockUntilSubscribed = true)
    override suspend fun updateAuth(token: String) = client.realtime.setAuth(token)
    override suspend fun dispose() {
        try { client.realtime.removeChannel(channel) }
        finally { client.close() }
    }
}

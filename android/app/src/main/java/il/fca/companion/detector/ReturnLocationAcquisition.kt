package il.fca.companion.detector

import android.location.Location
import android.os.CancellationSignal
import android.os.SystemClock
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** One cache-first acquisition; no home coordinates, persistence or retry loop. */
internal class ReturnLocationAcquisition(
    private val providers: Providers,
    private val diagnostic: (String) -> Unit,
    private val clock: () -> Long = SystemClock::elapsedRealtime,
    private val wallClock: () -> Long = System::currentTimeMillis,
    private val elapsedNanos: () -> Long = SystemClock::elapsedRealtimeNanos,
    private val await: (CountDownLatch, Long) -> Boolean = { latch, remaining ->
        latch.await(remaining, TimeUnit.MILLISECONDS)
    }
) {
    enum class Source(val tag: String) { GPS("gps"), NETWORK("network") }
    interface Providers {
        fun available(source: Source): Boolean
        fun enabled(source: Source): Boolean
        fun cached(source: Source): Location?
        fun request(source: Source, cancellation: CancellationSignal, started: () -> Unit,
                    callback: (Location?) -> Unit)
    }

    private val lock = Any()
    private val done = CountDownLatch(1)
    private val signals = Source.entries.associateWith { CancellationSignal() }
    private val pending = mutableSetOf<Source>()
    private val failures = mutableMapOf<Source, String>()
    private var outcome: ReturnWorker.LocationCheck? = null
    private var deadline = Long.MAX_VALUE

    private fun log(message: String) = ReturnWorker.diagnostic(diagnostic, message)
    private fun cancelAll() {
        signals.forEach { (source, signal) ->
            log("return_location_${source.tag}_cancel_requested")
            val result = runCatching { signal.cancel() }
            log("return_location_${source.tag}_cancel_${if (result.isSuccess) "completed" else "failed"}")
        }
    }
    private fun complete(result: ReturnWorker.LocationCheck): Boolean {
        val won = synchronized(lock) {
            if (outcome != null) false else { outcome = result; done.countDown(); true }
        }
        // Cancellation may wait for a callback: never call it while holding our lock.
        if (won) {
            cancelAll()
            if (result.reason == "location_timeout") log("return_location_shared_timeout")
        }
        return won
    }
    fun stop() { complete(ReturnWorker.LocationCheck(reason = "location_worker_stopped")) }
    private fun current(): ReturnWorker.LocationCheck? = synchronized(lock) { outcome }
    private fun validate(fix: Location?): String? = ReturnWorker.fixFailure(fix, wallClock(), elapsedNanos())
    private fun exceptionReason(error: Exception): String = when (error) {
        is InterruptedException -> "location_interrupted"
        is SecurityException -> "location_security_error"
        else -> "location_request_error"
    }

    fun acquire(fine: Boolean, background: Boolean): ReturnWorker.LocationCheck {
        deadline = clock() + 20_000L
        try {
            if (!fine) complete(ReturnWorker.LocationCheck(reason = "fine_permission_missing"))
            else if (!background) complete(ReturnWorker.LocationCheck(reason = "background_permission_missing"))
            current()?.let { return it }
            val active = mutableListOf<Source>()
            val cached = mutableListOf<Pair<Source, Location>>()
            for (source in Source.entries) {
                if (current() != null || clock() >= deadline) break
                try {
                    if (!providers.available(source)) { log("return_location_${source.tag}_unavailable"); continue }
                    if (!providers.enabled(source)) { log("return_location_${source.tag}_disabled"); continue }
                    active.add(source)
                    val fix = providers.cached(source)?.let(::Location)
                    val failure = validate(fix)
                    if (failure == null && fix != null) cached.add(source to fix)
                    else log("return_location_cache_${source.tag}_$failure")
                } catch (error: Exception) {
                    val reason = exceptionReason(error)
                    failures[source] = reason
                    log("return_location_${source.tag}_$reason")
                    if (error is InterruptedException) throw error
                }
            }
            current()?.let { return it }
            if (clock() >= deadline) {
                complete(ReturnWorker.LocationCheck(reason = "location_timeout"))
                return current()!!
            }
            val selected = cached.filter { validate(it.second) == null }.sortedWith(
                compareByDescending<Pair<Source, Location>> { it.second.elapsedRealtimeNanos }
                    .thenBy { it.second.accuracy }).firstOrNull()
            if (selected != null) {
                if (complete(ReturnWorker.LocationCheck(fix = selected.second)))
                    log("return_location_source_cache_${selected.first.tag}")
                return current()!!
            }
            synchronized(lock) { pending.addAll(active) }
            if (active.isEmpty()) complete(ReturnWorker.LocationCheck(
                reason = Source.entries.firstNotNullOfOrNull { failures[it] } ?: "location_unavailable"))
            for (source in active) {
                if (current() != null) break
                if (clock() >= deadline) { complete(ReturnWorker.LocationCheck(reason = "location_timeout")); break }
                try {
                    providers.request(source, signals.getValue(source),
                        { log("return_location_${source.tag}_request_started") }) { fix -> receive(source, fix) }
                    log("return_location_${source.tag}_request_submitted")
                } catch (error: Exception) {
                    val category = when (error) {
                        is SecurityException -> "security"
                        is RuntimeException -> "runtime"
                        else -> "other"
                    }
                    log("return_location_${source.tag}_request_failed_$category")
                    if (error is InterruptedException) throw error
                    receive(source, null, exceptionReason(error))
                }
            }
            val remaining = deadline - clock()
            if (current() == null && (remaining <= 0 || !await(done, remaining)))
                complete(ReturnWorker.LocationCheck(reason = "location_timeout"))
            return current()!!
        } catch (error: Exception) {
            complete(ReturnWorker.LocationCheck(reason = exceptionReason(error)))
            return current()!!
        } finally { cancelAll() }
    }

    private fun receive(source: Source, value: Location?, requestFailure: String? = null) {
        var message: String? = null
        var callbackMessage: String? = null
        var timedOut = false
        val finished = synchronized(lock) {
            if (outcome != null || !pending.remove(source)) {
                if (requestFailure == null) callbackMessage = "return_location_${source.tag}_callback_late_ignored"
                return@synchronized false
            }
            val fix = value?.let(::Location)
            val failure = requestFailure ?: validate(fix)
            if (requestFailure == null) callbackMessage = "return_location_${source.tag}_callback_" + when {
                value == null -> "null"
                failure != null -> "invalid_$failure"
                else -> "usable"
            }
            when {
                clock() >= deadline -> {
                    outcome = ReturnWorker.LocationCheck(reason = "location_timeout")
                    timedOut = true
                }
                failure == null -> {
                    outcome = ReturnWorker.LocationCheck(fix = fix)
                    message = "return_location_source_current_${source.tag}"
                }
                else -> {
                    failures[source] = failure
                    message = "return_location_current_${source.tag}_$failure"
                    if (pending.isEmpty()) {
                        val reason = Source.entries.firstNotNullOfOrNull { failures[it] } ?: "location_unavailable"
                        outcome = ReturnWorker.LocationCheck(reason = reason)
                    }
                }
            }
            (outcome != null).also { if (it) done.countDown() }
        }
        if (finished) cancelAll()
        callbackMessage?.let(::log)
        if (timedOut) log("return_location_shared_timeout")
        message?.let(::log)
    }
}

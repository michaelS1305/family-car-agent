package il.fca.companion.detector

import il.fca.companion.data.LocalStore
import il.fca.companion.data.ReturnCandidate

/** All calls, timers and completions are dispatched onto one serial executor. */
internal class ReturnController(private val ports: Ports) {
    fun interface Cancel { fun cancel() }
    interface Ports {
        fun candidates(): List<ReturnCandidate>
        fun invalid(candidate: ReturnCandidate): String?
        fun wall(): Long
        fun elapsed(): Long
        fun later(delay: Long, action: () -> Unit): Cancel
        fun acquire(candidate: ReturnCandidate, complete: (ReturnWorker.LocationCheck) -> Unit): Cancel
        fun decide(candidate: ReturnCandidate, result: ReturnWorker.LocationCheck): String
        fun abandon(candidate: ReturnCandidate)
        fun awake(remaining: Long)
        fun release()
        fun idle()
        fun diagnostic(message: String)
    }
    private class Active(val candidate: ReturnCandidate) {
        var grace: Cancel? = null
        var watchdog: Cancel? = null
        var acquisition: Cancel? = null
    }
    private var active: Active? = null
    private var closed = false
    private fun log(message: String) = ReturnWorker.diagnostic(ports::diagnostic, message)

    fun refresh() {
        if (closed) return
        val current = active
        if (current != null) {
            val invalid = ports.invalid(current.candidate)
            if (invalid == null) {
                log("return_fgs_duplicate_suppressed")
                return
            }
            log("return_fgs_candidate_invalid")
            end(current, invalid)
        }
        for (candidate in ports.candidates()) {
            val invalid = ports.invalid(candidate)
            if (invalid != null) {
                ports.abandon(candidate)
                log("return_fgs_candidate_invalid")
                log("return_fgs_stopped_$invalid")
                continue
            }
            val remaining = remainingLifetime(candidate, ports.wall(), ports.elapsed())
            if (remaining <= 0) {
                ports.abandon(candidate)
                log("return_fgs_watchdog_expired")
                continue
            }
            val slot = Active(candidate)
            active = slot
            ports.awake(remaining)
            slot.watchdog = ports.later(remaining) {
                if (active === slot) {
                    log("return_fgs_watchdog_expired")
                    end(slot, "watchdog")
                    refresh()
                }
            }
            slot.grace = ports.later(remainingGrace(candidate, ports.wall(), ports.elapsed())) { begin(slot) }
            return
        }
        ports.idle()
    }

    private fun begin(slot: Active) {
        if (closed || active !== slot) return
        val invalid = ports.invalid(slot.candidate)
        if (invalid != null) { end(slot, invalid); refresh(); return }
        if (remainingLifetime(slot.candidate, ports.wall(), ports.elapsed()) <= 0) {
            log("return_fgs_watchdog_expired"); end(slot, "watchdog"); refresh(); return
        }
        val grace = remainingGrace(slot.candidate, ports.wall(), ports.elapsed())
        if (grace > 0) {
            slot.grace = ports.later(grace) { begin(slot) }
            return
        }
        log("return_fgs_acquisition_started")
        slot.acquisition = ports.acquire(slot.candidate) { result ->
            if (!closed && active === slot) {
                val reason = ports.invalid(slot.candidate)
                if (remainingLifetime(slot.candidate, ports.wall(), ports.elapsed()) <= 0) {
                    log("return_fgs_watchdog_expired"); end(slot, "watchdog")
                } else if (reason != null) end(slot, reason)
                else end(slot, ports.decide(slot.candidate, result))
                refresh()
            }
        }
    }

    private fun end(slot: Active, reason: String) {
        if (active !== slot) return
        active = null // Late completion/cancellation can never act on a successor.
        slot.grace?.cancel()
        slot.watchdog?.cancel()
        slot.acquisition?.cancel()
        ports.abandon(slot.candidate) // Conditional SQL cannot erase a newer candidate.
        ports.release()
        log("return_fgs_stopped_$reason")
    }

    fun close() {
        closed = true
        // Service destruction is not proof of failure. Leave the durable candidate
        // recoverable, with its ORIGINAL deadlines, after process/service loss.
        active?.let {
            active = null
            it.grace?.cancel(); it.watchdog?.cancel(); it.acquisition?.cancel()
        }
        ports.release()
    }

    companion object {
        fun remainingGrace(c: ReturnCandidate, wall: Long, elapsed: Long): Long =
            maxOf(0L, c.due - wall, c.elapsedDue - elapsed)
        fun remainingLifetime(c: ReturnCandidate, wall: Long, elapsed: Long): Long =
            minOf(c.due + LocalStore.RETURN_GRACE_MS - wall,
                c.elapsedDue + LocalStore.RETURN_GRACE_MS - elapsed)
    }
}

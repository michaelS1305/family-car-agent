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
        fun retryReady(candidate: ReturnCandidate): Boolean
        fun claim(candidate: ReturnCandidate): Boolean
        fun defer(candidate: ReturnCandidate)
        fun schedule(candidate: ReturnCandidate)
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
            val remaining = remainingLifetime(candidate, ports.wall(), ports.elapsed())
            if (remaining <= 0) {
                ports.abandon(candidate)
                log("return_fgs_watchdog_expired")
                continue
            }
            if (invalid != null && ReturnOutcome.from(invalid).disposition != ReturnDisposition.DEFERRED) {
                ports.abandon(candidate)
                log("return_fgs_stopped_$invalid")
                continue
            }
            if (!ports.retryReady(candidate)) { ports.schedule(candidate); continue }
            if (invalid != null) {
                if (ports.claim(candidate)) ports.defer(candidate)
                ports.schedule(candidate)
                log("return_fgs_stopped_$invalid")
                continue
            }
            val slot = Active(candidate)
            active = slot
            // Candidate lifetime is NOT a foreground/wake-lock lifetime.
            val attemptBudget = minOf(remaining,
                remainingGrace(candidate, ports.wall(), ports.elapsed()) + LocalStore.RETURN_ATTEMPT_MS)
            ports.awake(attemptBudget)
            slot.watchdog = ports.later(attemptBudget) {
                if (active === slot) {
                    log("return_fgs_watchdog_expired")
                    end(slot, if (remainingLifetime(candidate, ports.wall(), ports.elapsed()) <= 0) "expired" else "watchdog")
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
            log("return_fgs_watchdog_expired"); end(slot, "expired"); refresh(); return
        }
        val grace = remainingGrace(slot.candidate, ports.wall(), ports.elapsed())
        if (grace > 0) {
            slot.grace = ports.later(grace) { begin(slot) }
            return
        }
        log("return_fgs_acquisition_started")
        if (!ports.claim(slot.candidate)) { end(slot, "retry_not_ready", false); refresh(); return }
        ports.schedule(slot.candidate) // Recover the reserved attempt after process loss.
        slot.acquisition = ports.acquire(slot.candidate) { result ->
            if (!closed && active === slot) {
                val reason = ports.invalid(slot.candidate)
                if (remainingLifetime(slot.candidate, ports.wall(), ports.elapsed()) <= 0) {
                    log("return_fgs_watchdog_expired"); end(slot, "expired")
                } else end(slot, reason ?: ports.decide(slot.candidate, result))
                refresh()
            }
        }
    }

    private fun end(slot: Active, reason: String, abandon: Boolean = true) {
        if (active !== slot) return
        active = null // Late completion/cancellation can never act on a successor.
        slot.grace?.cancel()
        slot.watchdog?.cancel()
        slot.acquisition?.cancel()
        if (abandon) {
            if (ReturnOutcome.from(reason).disposition == ReturnDisposition.DEFERRED) {
                ports.defer(slot.candidate)
                ports.schedule(slot.candidate)
            } else ports.abandon(slot.candidate)
        } else ports.schedule(slot.candidate)
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
            LocalStore.returnLifetime(c, wall, elapsed)
    }
}

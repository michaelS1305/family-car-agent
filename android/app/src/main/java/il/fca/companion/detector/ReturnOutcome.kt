package il.fca.companion.detector

internal enum class ReturnDisposition { QUEUED, DEFERRED, TERMINAL, EXPIRED }
internal data class ReturnOutcome(val disposition: ReturnDisposition, val reason: String) {
    companion object {
        private val transient = setOf(
            "location_timeout", "location_unavailable", "location_too_old",
            "location_accuracy_missing", "location_accuracy_too_low",
            "location_worker_stopped", "location_interrupted", "location_security_error",
            "location_request_error", "fine_permission_missing", "background_permission_missing",
            "location_disabled", "home_cache_missing", "home_cache_expired", "watchdog"
        )
        fun from(reason: String) = ReturnOutcome(when {
            reason == "queued" -> ReturnDisposition.QUEUED
            reason == "expired" -> ReturnDisposition.EXPIRED
            reason in transient -> ReturnDisposition.DEFERRED
            else -> ReturnDisposition.TERMINAL
        }, reason)
    }
}

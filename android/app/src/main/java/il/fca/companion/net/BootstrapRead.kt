package il.fca.companion.net

import java.net.ConnectException
import java.net.SocketTimeoutException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive

/** Only the backend GET /api/me. Authentication refresh and writes are outside this policy. */
internal object BootstrapRead {
    suspend fun <T> run(current: () -> Boolean, pause: suspend (Long) -> Unit = { delay(it) },
                        request: suspend () -> T): T {
        for (attempt in 0..2) {
            currentCoroutineContext().ensureActive()
            check(current()) { "Session changed" }
            try {
                val result = request()
                currentCoroutineContext().ensureActive()
                check(current()) { "Session changed" }
                return result
            } catch (error: Exception) {
                val transient = when (error) {
                    is OnboardingFailure -> error.status in setOf(502, 503, 504)
                    is SocketTimeoutException, is ConnectException -> true
                    else -> false
                }
                if (!transient || attempt == 2 || !current()) throw error
                pause(1000L shl attempt)
            }
        }
        error("Unreachable")
    }
}

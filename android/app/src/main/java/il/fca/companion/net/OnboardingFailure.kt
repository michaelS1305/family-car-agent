package il.fca.companion.net

import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection

// Ephemeral UI-only metadata. Never put server text in Throwable.message/cause,
// diagnostic logs, saved state, or persistent storage. Delivery still uses HttpFailure.
class OnboardingFailure private constructor(
    val status: Int,
    val missingAccount: Boolean = false,
    val code: String? = null,
    val uiMessage: String? = null,
    val attemptsRemaining: Int? = null,
    val lockedUntil: String? = null,
    val retryAfterSeconds: Int? = null,
) : IOException("HTTP $status") {
    companion object {
        private val postPaths = setOf(
            "/api/onboarding/create-family", "/api/onboarding/create-family/address",
            "/api/onboarding/join-family/start", "/api/onboarding/join-family/family-name",
            "/api/onboarding/join-family/address", "/api/onboarding/join-family/address-confirmation",
            "/api/onboarding/join-family/code", "/api/onboarding/join-family/complete",
        )
        internal fun supports(path: String, method: String) =
            (path == "/api/me" && method == "GET") || (path in postPaths && method == "POST")

        internal fun read(connection: HttpURLConnection, status: Int, path: String): OnboardingFailure {
            return try {
                val bytes = connection.errorStream?.use { it.readNBytes(8193) }
                if (bytes == null || bytes.size > 8192) OnboardingFailure(status)
                else parse(status, path, bytes.toString(Charsets.UTF_8))
            } catch (_: Exception) { OnboardingFailure(status) }
        }

        internal fun parse(status: Int, path: String, body: String): OnboardingFailure = try {
            val detail = JSONObject(body).opt("detail")
            if (path == "/api/me") {
                OnboardingFailure(status, missingAccount = status == 403 && detail is String &&
                    detail in setOf("Authenticated user is not registered in the application",
                        "Authenticated user is not assigned to a family"),
                    code = "ACCOUNT_UNAVAILABLE".takeIf {
                        status == 403 && detail is JSONObject && detail.opt("code") == it
                    })
            } else if (path in postPaths && detail is JSONObject) {
                fun text(name: String, max: Int) = (detail.opt(name) as? String)
                    ?.takeIf { it.isNotBlank() && it.length <= max && it.none { c -> c.isISOControl() } }
                fun count(name: String) = (detail.opt(name) as? Int)?.takeIf { it >= 0 }
                OnboardingFailure(status,
                    code = text("code", 80)?.takeIf { it.matches(Regex("[A-Za-z0-9_]+")) },
                    uiMessage = text("message", 1000),
                    attemptsRemaining = count("attempts_remaining"),
                    lockedUntil = text("locked_until", 64)?.takeIf {
                        runCatching { java.time.OffsetDateTime.parse(it) }.isSuccess
                    },
                    retryAfterSeconds = count("retry_after_seconds"))
            } else OnboardingFailure(status)
        } catch (_: Exception) { OnboardingFailure(status) }
    }
}

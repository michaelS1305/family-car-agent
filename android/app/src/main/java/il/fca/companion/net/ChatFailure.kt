package il.fca.companion.net

import java.io.IOException
import java.net.HttpURLConnection
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import org.json.JSONObject

/** Structured fields are memory-only. Exception text never contains the response body. */
class ChatFailure(
    val kind: Kind,
    val status: Int? = null,
    val code: String? = null,
    val serverMessage: String? = null,
    val retryAfterSeconds: Long? = null,
    val retryable: Boolean = false,
) : IOException("CHAT_${kind.name}") {
    enum class Kind { AUTH, VALIDATION, IN_PROGRESS, RATE_LIMITED, UNCERTAIN, TERMINAL, CONFLICT, UNKNOWN }
    companion object {
        internal fun read(connection: HttpURLConnection, status: Int): ChatFailure {
            val body = try { connection.errorStream?.use {
                val bytes = it.readNBytes(16385)
                if (bytes.size <= 16384) bytes.toString(Charsets.UTF_8) else null
            } } catch (_: Exception) { null }
            return parse(status, body, connection.getHeaderField("Retry-After"))
        }
        internal fun parse(status: Int, body: String?, retryHeader: String?): ChatFailure {
            val detail = try { JSONObject(body ?: "").opt("detail") } catch (_: Exception) { null }
            val obj = detail as? JSONObject
            val code = (obj?.opt("code") as? String)?.takeIf { it.length <= 128 }
            val message = ((obj?.opt("message") as? String) ?: (detail as? String))?.takeIf { it.length <= 4000 }
            val seconds = (obj?.opt("retry_after_seconds") as? Number)?.toDouble()
                ?.takeIf { it.isFinite() && it >= 0 && it <= Int.MAX_VALUE }?.let { kotlin.math.ceil(it).toLong() }
            val header = retryHeader?.toLongOrNull()?.takeIf { it in 0..Int.MAX_VALUE.toLong() }
                ?: try { retryHeader?.let {
                    ((ZonedDateTime.parse(it, DateTimeFormatter.RFC_1123_DATE_TIME).toInstant().toEpochMilli() -
                        System.currentTimeMillis() + 999) / 1000).coerceIn(0, Int.MAX_VALUE.toLong())
                } } catch (_: Exception) { null }
            val delay = listOfNotNull(seconds, header).maxOrNull()
            val kind = when {
                status == 401 || status == 403 -> Kind.AUTH
                status == 400 || status == 422 -> Kind.VALIDATION
                code in setOf("IDEMPOTENCY_KEY_REUSED", "REQUEST_CONTEXT_CHANGED") -> Kind.CONFLICT
                code in setOf("AI_UNAVAILABLE", "CHAT_ATTEMPTS_EXHAUSTED") -> Kind.TERMINAL
                code in setOf("CHAT_IN_PROGRESS", "CHAT_CONCURRENCY_LIMITED", "CHAT_LEASE_LOST") -> Kind.IN_PROGRESS
                status == 429 -> Kind.RATE_LIMITED
                code in setOf("CHAT_RECOVERY_REQUIRED", "GEMINI_CAPACITY_UNAVAILABLE") -> Kind.UNCERTAIN
                else -> Kind.UNKNOWN
            }
            return ChatFailure(kind, status, code, message, delay,
                kind in setOf(Kind.IN_PROGRESS, Kind.RATE_LIMITED, Kind.UNCERTAIN) || status >= 500 && kind == Kind.UNKNOWN)
        }
        fun uncertain() = ChatFailure(Kind.UNCERTAIN, code = "RESPONSE_UNCERTAIN", retryable = true)
    }
}

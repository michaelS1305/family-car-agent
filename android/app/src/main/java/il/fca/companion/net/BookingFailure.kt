package il.fca.companion.net

import java.io.IOException
import java.net.HttpURLConnection
import org.json.JSONObject

// Booking-only, ephemeral allowlisted codes. No server messages, choices or bodies retained.
internal class BookingFailure(val status: Int, val code: String? = null) : IOException("HTTP $status") {
    companion object {
        private val codes = mapOf("RESERVATION_CONFLICT" to 409, "VEHICLE_REQUIRED" to 409,
            "RESERVATION_AMBIGUOUS" to 409, "VEHICLE_NOT_FOUND_OR_UNAVAILABLE" to 404,
            "RESERVATION_NOT_FOUND_OR_UNAVAILABLE" to 404, "INVALID_RESERVATION_TIME" to 422,
            "RESERVATION_TIME_IN_PAST" to 422)
        fun supports(path: String, method: String) =
            (path == "/api/reservations" && method in setOf("POST", "PATCH")) ||
                (path == "/api/reservations/cancel" && method == "POST")
        fun parse(status: Int, body: String): BookingFailure = try {
            val code = JSONObject(body).optJSONObject("detail")?.opt("code") as? String
            BookingFailure(status, code?.takeIf { codes[it] == status })
        } catch (_: Exception) { BookingFailure(status) }
        fun read(connection: HttpURLConnection, status: Int): BookingFailure = try {
            val bytes = connection.errorStream?.use { it.readNBytes(4097) }
            if (bytes == null || bytes.size > 4096) BookingFailure(status)
            else parse(status, bytes.toString(Charsets.UTF_8))
        } catch (_: Exception) { BookingFailure(status) }
    }
}

// Matches the existing one-time 401 refresh, without retrying transport/server failures.
internal fun bookingAuthenticated(attempt: (Boolean) -> String): String {
    try { return attempt(false) }
    catch (e: BookingFailure) { if (e.status != 401) throw e }
    catch (e: HttpFailure) { if (e.status != 401) throw e }
    return attempt(true)
}

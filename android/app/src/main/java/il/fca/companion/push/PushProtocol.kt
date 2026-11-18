package il.fca.companion.push

import org.json.JSONObject
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.UUID

internal const val PUSH_ROOT = "/api/native-push"
internal fun validRef(value: String): Boolean = runCatching {
    UUID.fromString(value).toString() == value.lowercase()
}.getOrDefault(false)

internal data class PushEvent(val ref: String, val type: String, val expires: Long,
                              val actor: String, val vehicle: String, val scheduled: String = "") {
    fun text() = when (type) {
        "vehicle_taken" -> "$actor לקח את $vehicle"
        "vehicle_returned" -> "$actor החזיר את $vehicle"
        "reservation_reminder" -> "תזכורת להזמנת $vehicle ב־$scheduled"
        "maintenance_reminder" -> "תזכורת לטיפול ב־$vehicle בתאריך $scheduled"
        else -> error("Unsupported notification")
    }
    companion object {
        fun parse(value: JSONObject, now: Long): PushEvent? = runCatching {
            val ref = value.getString("event_ref")
            val vehicle = value.getString("vehicle_ref")
            val type = value.getString("type")
            val occurred = Instant.parse(value.getString("occurred_at")).toEpochMilli()
            val expires = Instant.parse(value.getString("expires_at")).toEpochMilli()
            require(validRef(ref) && validRef(vehicle))
            require(type in setOf("vehicle_taken", "vehicle_returned", "reservation_reminder", "maintenance_reminder"))
            require(expires > now && expires > occurred && expires - occurred <= 300_000)
            val actorName = value.getString("actor_name")
            val vehicleName = value.getString("vehicle_name")
            require(actorName.isNotBlank() && vehicleName.isNotBlank())
            val scheduled = if (type.endsWith("_reminder")) {
                val instant = Instant.parse(value.getString("scheduled_for"))
                require(instant.toEpochMilli() >= expires && instant.toEpochMilli() > now)
                instant.atZone(ZoneId.of("Asia/Jerusalem")).format(DateTimeFormatter.ofPattern(
                    if (type == "reservation_reminder") "dd/MM HH:mm" else "dd/MM/yyyy"))
            } else ""
            PushEvent(ref, type, expires, actorName.take(120), vehicleName.take(120), scheduled)
        }.getOrNull()
    }
}

internal fun refreshSignal(data: Map<String, String>) = data == mapOf("kind" to "refresh", "version" to "1")
internal fun challengeSignal(data: Map<String, String>): Boolean =
    data.keys == setOf("kind", "challenge_ref", "installation_ref", "nonce", "generation") &&
        data["kind"] == "registration_challenge" && validRef(data["challenge_ref"].orEmpty()) &&
        validRef(data["installation_ref"].orEmpty()) &&
        data["nonce"].orEmpty().matches(Regex("[A-Za-z0-9_-]{43}")) &&
        (data["generation"]?.toLongOrNull() ?: 0) in 1 until Long.MAX_VALUE

internal fun registrationBody(ref: String, request: String, token: String) = JSONObject()
    .put("installation_ref", ref).put("request_id", request).put("platform", "android").put("token", token)

internal fun eventsPath(ref: String, generation: Long, cursor: String?): String {
    require(validRef(ref) && generation > 0 && (cursor == null || validRef(cursor)))
    return "$PUSH_ROOT/installations/$ref/events?expected_generation=$generation&limit=20" +
        (cursor?.let { "&cursor=$it" } ?: "")
}

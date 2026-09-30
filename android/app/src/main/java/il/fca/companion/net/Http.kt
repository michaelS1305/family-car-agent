package il.fca.companion.net

import java.net.HttpURLConnection
import java.net.URI
import java.io.IOException
import org.json.JSONObject

class HttpFailure(val status: Int, val diagnosticCode: String? = null) : IOException("HTTP $status")

object Http {
    private val diagnosticCodes = setOf(
        "DEVICE_NOT_FOUND_OR_UNAVAILABLE", "VEHICLE_NOT_FOUND_OR_UNAVAILABLE",
        "DEVICE_OR_VEHICLE_UNAVAILABLE"
    )
    internal fun failure(connection: HttpURLConnection, status: Int): HttpFailure {
        // Bound memory; never retain the body/message or attach parsing exceptions.
        val code = try {
            connection.errorStream?.use { stream ->
                val bytes = stream.readNBytes(4097)
                if (bytes.size > 4096) null else {
                    val detail = JSONObject(bytes.toString(Charsets.UTF_8)).opt("detail")
                    when {
                        detail is String && detail == "Not Found" -> "route_not_found"
                        detail is JSONObject -> (detail.opt("code") as? String)?.takeIf { it in diagnosticCodes }
                        else -> null
                    }
                }
            }
        } catch (_: Exception) { null }
        return HttpFailure(status, code)
    }
    // No redirects, logging, retries or exception messages containing URL/body.
    fun request(base: String, path: String, method: String = "GET", body: JSONObject? = null,
                bearer: String? = null, apiKey: String? = null): String {
        val origin = URI(base)
        require(origin.scheme == "https" && origin.host != null && origin.userInfo == null &&
            origin.rawQuery == null && origin.rawFragment == null)
        val connection = URI(base.trimEnd('/') + path).toURL().openConnection() as HttpURLConnection
        try {
            connection.instanceFollowRedirects = false
            connection.requestMethod = method
            connection.connectTimeout = 15000
            connection.readTimeout = 15000
            connection.setRequestProperty("Accept", "application/json")
            bearer?.let { connection.setRequestProperty("Authorization", "Bearer $it") }
            apiKey?.let { connection.setRequestProperty("apikey", it) }
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            val status = connection.responseCode
            if (status !in 200..299) throw failure(connection, status)
            return connection.inputStream.bufferedReader().use { it.readText() }
        } finally { connection.disconnect() }
    }
}

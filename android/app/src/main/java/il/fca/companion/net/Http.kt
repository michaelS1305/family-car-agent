package il.fca.companion.net

import java.net.HttpURLConnection
import java.net.URI
import java.io.IOException
import org.json.JSONObject

class HttpFailure(val status: Int) : IOException("HTTP $status")

object Http {
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
            if (connection.responseCode !in 200..299) throw HttpFailure(connection.responseCode)
            return connection.inputStream.bufferedReader().use { it.readText() }
        } finally { connection.disconnect() }
    }
}

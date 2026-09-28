package il.fca.companion.net

import il.fca.companion.BuildConfig
import il.fca.companion.auth.SessionStore
import org.json.JSONObject

class FcaApi(private val auth: SessionStore) {
    fun call(owner: String, path: String, method: String = "GET", body: JSONObject? = null): String {
        try { return Http.request(BuildConfig.FCA_BASE_URL, path, method, body, auth.access(owner)) }
        catch (e: HttpFailure) {
            if (e.status != 401) throw e
            // The retry uses the exact same durable event/request payload.
            return Http.request(BuildConfig.FCA_BASE_URL, path, method, body, auth.access(owner, true))
        }
    }
}

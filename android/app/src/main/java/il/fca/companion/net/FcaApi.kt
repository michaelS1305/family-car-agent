package il.fca.companion.net

import il.fca.companion.BuildConfig
import il.fca.companion.auth.SessionStore
import org.json.JSONObject

class FcaApi(private val auth: SessionStore) {
    internal fun chat(owner: String, path: String, method: String, body: JSONObject?): String {
        fun attempt(force: Boolean): String {
            val token = try { auth.access(owner, force) }
            catch (e: HttpFailure) { throw e }
            catch (e: java.io.IOException) { throw e }
            catch (_: Exception) { throw ChatFailure(ChatFailure.Kind.AUTH, code = "SESSION_UNAVAILABLE") }
            return Http.chatRequest(BuildConfig.FCA_BASE_URL, path, method, body, token)
        }
        try { return attempt(false) }
        catch (e: ChatFailure) {
            if (e.status != 401) throw e
            return attempt(true)
        } catch (e: HttpFailure) {
            if (e.status != 401) throw e
            return attempt(true)
        }
    }
    fun onboarding(owner: String, path: String, method: String = "GET", body: JSONObject? = null): String {
        require(OnboardingFailure.supports(path, method))
        try { return Http.onboardingRequest(BuildConfig.FCA_BASE_URL, path, method, body, auth.access(owner)) }
        catch (e: OnboardingFailure) {
            if (e.status != 401) throw e
            return Http.onboardingRequest(BuildConfig.FCA_BASE_URL, path, method, body, auth.access(owner, true))
        }
        catch (e: HttpFailure) {
            // SessionStore's own refresh request still uses the original HTTP path.
            // Preserve call()'s handling if access() itself raises HTTP 401.
            if (e.status != 401) throw e
            return Http.onboardingRequest(BuildConfig.FCA_BASE_URL, path, method, body, auth.access(owner, true))
        }
    }
    fun call(owner: String, path: String, method: String = "GET", body: JSONObject? = null): String {
        try { return Http.request(BuildConfig.FCA_BASE_URL, path, method, body, auth.access(owner)) }
        catch (e: HttpFailure) {
            if (e.status != 401) throw e
            // The retry uses the exact same durable event/request payload.
            return Http.request(BuildConfig.FCA_BASE_URL, path, method, body, auth.access(owner, true))
        }
    }
}

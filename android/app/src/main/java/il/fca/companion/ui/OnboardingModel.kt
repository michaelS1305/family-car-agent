package il.fca.companion.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import il.fca.companion.net.OnboardingFailure
import il.fca.companion.net.AddressVerification
import il.fca.companion.net.ResolvedAddress
import org.json.JSONObject

enum class EntryScreen { INTRO, LOGIN, ONBOARDING, SUCCESS, BOOTSTRAP, AUTHENTICATED_APP }

interface OnboardingGateway {
    suspend fun request(path: String, method: String = "GET", body: JSONObject? = null): JSONObject
    suspend fun activate()
    suspend fun clearSession()
}

// Memory-only state, retained by the entry ViewModel across configuration changes.
// No SavedStateHandle / rememberSaveable for private form or server data.
class OnboardingModel(private val gateway: OnboardingGateway) {
    var screen by mutableStateOf(EntryScreen.INTRO); private set
    var route by mutableStateOf(LoginRoute.EXISTING_ACCOUNT); private set
    var step by mutableStateOf(1); private set
    private var working by mutableStateOf(false)
    var authenticating by mutableStateOf(false)
    val busy get() = working || authenticating
    var error by mutableStateOf<String?>(null); private set
    var failure by mutableStateOf<OnboardingFailure?>(null); private set
    var familyName by mutableStateOf("")
    var address by mutableStateOf("")
    var userName by mutableStateOf("")
    var authenticatedName by mutableStateOf(""); private set
    var authenticatedFamilyId by mutableStateOf<Long?>(null); private set
    var joinCode by mutableStateOf("")
    var consent by mutableStateOf(false)
    var resolvedAddress by mutableStateOf(""); private set
    var createdCode by mutableStateOf(""); private set
    private var resolution: ResolvedAddress? = null
    private var completed = false
    val totalSteps get() = if (route == LoginRoute.CREATE_FAMILY) 4 else 5

    fun select(selected: LoginRoute) {
        if (busy) return
        clearPrivateState()
        authenticatedName = ""
        authenticatedFamilyId = null
        route = selected; screen = EntryScreen.LOGIN; clearError()
    }
    fun back() {
        if (busy) return
        clearError()
        when (screen) {
            EntryScreen.LOGIN -> { screen = EntryScreen.INTRO; clearPrivateState() }
            EntryScreen.ONBOARDING -> if (step > 1) step-- else screen = EntryScreen.LOGIN
            else -> Unit
        }
    }
    fun genericFailure() { error = "יש בעיה, נסה שוב" }
    private fun authenticatedApp() { clearPrivateState(); screen = EntryScreen.AUTHENTICATED_APP }
    fun leaveAuthenticatedApp() {
        if (screen in setOf(EntryScreen.AUTHENTICATED_APP, EntryScreen.BOOTSTRAP, EntryScreen.SUCCESS)) {
            authenticatedName = ""
            authenticatedFamilyId = null
            clearPrivateState(); clearError(); screen = EntryScreen.INTRO
        }
    }
    suspend fun bootstrap(isCurrent: () -> Boolean) = perform {
        screen = EntryScreen.BOOTSTRAP
        try {
            check(isCurrent())
            val me = gateway.request("/api/me")
            if (!isCurrent()) { leaveAuthenticatedApp(); return@perform }
            check(!me.isNull("family_id"))
            // Already active: do not reset acquisition state or the home cache.
            authenticatedName = me.optString("name", "")
            authenticatedFamilyId = me.getLong("family_id")
            authenticatedApp()
        } catch (e: OnboardingFailure) {
            if (!isCurrent()) { leaveAuthenticatedApp(); return@perform }
            if (e.code == "ACCOUNT_UNAVAILABLE") { unavailableAccount(); return@perform }
            if (!e.missingAccount) throw e
            missingAccount()
        } catch (e: Exception) {
            if (!isCurrent()) { leaveAuthenticatedApp(); return@perform }
            throw e
        }
    }
    private suspend fun missingAccount() {
        authenticatedName = ""
        authenticatedFamilyId = null
        gateway.clearSession(); clearPrivateState(); screen = EntryScreen.INTRO
        error = "לא נמצא חשבון FCA פעיל. אפשר ליצור משפחה או להצטרף למשפחה."
    }
    private suspend fun unavailableAccount() {
        gateway.clearSession()
        authenticatedName = ""; authenticatedFamilyId = null
        clearPrivateState(); screen = EntryScreen.INTRO
        error = "החשבון אינו זמין או נמצא בתהליך מחיקה."
    }
    private fun clearError() { error = null; failure = null }
    private fun clearPrivateState() {
        familyName = ""; address = ""; userName = ""; joinCode = ""; consent = false
        resolution = null; resolvedAddress = ""; createdCode = ""; completed = false; step = 1
    }
    suspend fun authenticated(selected: LoginRoute) = perform {
        route = selected
        when (selected) {
            LoginRoute.EXISTING_ACCOUNT -> {
                try {
                    val me = gateway.request("/api/me")
                    check(!me.isNull("family_id"))
                    gateway.activate()
                    authenticatedName = me.optString("name", "")
                    authenticatedFamilyId = me.getLong("family_id")
                    authenticatedApp()
                } catch (e: OnboardingFailure) {
                    if (e.code == "ACCOUNT_UNAVAILABLE") { unavailableAccount(); return@perform }
                    if (!e.missingAccount) throw e
                    missingAccount()
                }
            }
            LoginRoute.CREATE_FAMILY -> { step = 1; screen = EntryScreen.ONBOARDING }
            LoginRoute.JOIN_FAMILY -> applyJoin(gateway.request(joinPath("start"), "POST"))
        }
    }
    suspend fun changeAddress() = perform {
        if (route == LoginRoute.JOIN_FAMILY) {
            applyJoin(gateway.request(joinPath("address-confirmation"), "POST", JSONObject().put("confirmed", false)))
        } else { step = 2; resolution = null }
    }
    suspend fun next() = perform {
        if (screen == EntryScreen.SUCCESS) { authenticatedApp(); return@perform }
        if (completed) { finishAccount(); return@perform }
        check(screen == EntryScreen.ONBOARDING)
        if (step == 1 && !validName(familyName)) {
            error = "שם המשפחה יכול להכיל אותיות, רווחים, מקף או גרש, ללא ספרות."; return@perform
        }
        if (step == 2 && (address.isBlank() || address.codePointCount(0, address.length) > 200)) {
            error = if (address.isBlank()) "יש לכתוב כתובת בפורמט: עיר, רחוב, מספר בית."
                else "הכתובת ארוכה מדי. ניתן להזין עד 200 תווים."; return@perform
        }
        if (step == totalSteps && (!validName(userName) || !consent)) {
            error = if (!consent) "כדי להשלים את ההרשמה, יש לאשר את הצהרת הכשירות לשימוש ברכב."
                else "השם הפרטי יכול להכיל אותיות, רווחים, מקף או גרש, ללא ספרות."
            return@perform
        }
        if (route == LoginRoute.CREATE_FAMILY) {
            when (step) {
                1 -> step = 2
                2 -> {
                    val result = AddressVerification.resolve(address, creatingFamily = true) { path, body ->
                        gateway.request(path, "POST", body)
                    }
                    resolvedAddress = result.display; resolution = result; step = 3
                }
                3 -> step = 4
                4 -> {
                    gateway.request("/api/onboarding/create-family", "POST", JSONObject()
                        .put("family_name", familyName).put("user_name", userName)
                        .put("address_resolution_token", checkNotNull(resolution).token))
                    completed = true; finishAccount()
                }
            }
        } else {
            val (suffix, payload) = when (step) {
                1 -> "family-name" to JSONObject().put("family_name", familyName)
                2 -> "address" to JSONObject().put("home_address", address)
                3 -> "address-confirmation" to JSONObject().put("confirmed", true)
                // Invalid attempts still reach the authoritative server counter.
                4 -> "code" to JSONObject().put("family_code", joinCode)
                else -> "complete" to JSONObject().put("user_name", userName)
            }
            val result = gateway.request(joinPath(suffix), "POST", payload)
            if (step == 5) { completed = true; finishAccount() } else applyJoin(result)
        }
    }
    private suspend fun finishAccount() {
        val me = gateway.request("/api/me")
        check(!me.isNull("family_id"))
        if (route == LoginRoute.CREATE_FAMILY) createdCode = gateway.request("/api/family").getString("family_code")
        gateway.activate()
        authenticatedName = me.optString("name", "")
        authenticatedFamilyId = me.getLong("family_id")
        resolution = null; joinCode = ""; screen = EntryScreen.SUCCESS
    }
    suspend fun logout() = perform {
        gateway.clearSession()
        leaveAuthenticatedApp()
    }
    private fun joinPath(suffix: String) = "/api/onboarding/join-family/$suffix"
    private fun applyJoin(result: JSONObject) {
        step = when (result.getString("step")) {
            "family_name" -> 1; "address" -> 2; "address_confirmed" -> 3
            "family_code" -> 4; "user_name" -> 5
            else -> error("Unexpected onboarding state")
        }
        if (!result.isNull("family_name")) familyName = result.getString("family_name")
        if (!result.isNull("resolved_address")) resolvedAddress = result.getString("resolved_address")
        if (address.isBlank() && !result.isNull("normalized_address")) address = result.getString("normalized_address")
        screen = EntryScreen.ONBOARDING
    }
    private suspend fun perform(action: suspend () -> Unit) {
        if (busy) return
        working = true; clearError()
        try { action() }
        catch (e: OnboardingFailure) {
            failure = e; error = e.uiMessage ?: "יש בעיה, נסה שוב"
            if (route == LoginRoute.CREATE_FAMILY) {
                when (e.code) {
                    "INVALID_FAMILY_NAME" -> step = 1
                    "ADDRESS_RESOLUTION_EXPIRED" -> { resolution = null; step = 2 }
                    "INVALID_USER_NAME" -> step = 4
                }
            }
            if (route == LoginRoute.JOIN_FAMILY && e.code == "INVALID_JOIN_STEP") {
                // Reconcile without resetting attempts or manufacturing a local session.
                try { applyJoin(gateway.request(joinPath("start"), "POST")) } catch (_: Exception) { /* Keep error. */ }
            }
        }
        catch (_: Exception) { genericFailure() }
        finally { working = false }
    }

    companion object {
        // Same Unicode letters/separators as web onboarding; backend remains authoritative.
        internal fun validName(value: String): Boolean {
            if (value.codePointCount(0, value.length) > 100) return false
            val normalized = java.text.Normalizer.normalize(value, java.text.Normalizer.Form.NFC)
                // Android uses ICU, which rejects the JVM-only embedded (?U) flag.
                // Explicit Unicode separators + whitespace controls work on both runtimes.
                .trim().replace(Regex("[\\p{Z}\\t\\n\\u000B\\f\\r\\u0085]+"), " ").replace(Regex("[’׳]"), "'")
                .replace(Regex("[‐‑‒–—−]"), "-")
            val points = normalized.codePoints().toArray()
            if (points.isEmpty() || !Character.isLetter(points[0])) return false
            return points.indices.all { index ->
                val point = points[index]
                if (Character.isLetter(point)) true else {
                    val previous = index > 0 && Character.isLetter(points[index - 1])
                    val next = index < points.lastIndex && Character.isLetter(points[index + 1])
                    when (point) {
                        39 -> previous && (index == points.lastIndex || next)
                        32, 45 -> previous && next
                        else -> false
                    }
                }
            }
        }
    }
}

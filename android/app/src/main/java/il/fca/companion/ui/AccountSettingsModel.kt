package il.fca.companion.ui

import androidx.compose.runtime.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import org.json.JSONObject

internal data class AccountIdentity(val owner: String, val family: Long)
internal interface AccountSettingsGateway {
    suspend fun email(owner: String): String?
    suspend fun request(owner: String, method: String, preview: Boolean = false): JSONObject
}

internal data class AccountSettingsState(
    val email: String? = null,
    val dialog: Boolean = false,
    val busy: Boolean = false,
    val consequence: String? = null,
    val phase: String? = null,
    val uncertain: Boolean = false,
    val error: String? = null,
) {
    val protected: Boolean get() = uncertain || phase in setOf("draining", "auth_pending", "completed")
}

/** Activity-owned; navigation/recomposition cannot discard an uncertain deletion. No persistence. */
internal class AccountSettingsModel(
    private val gateway: AccountSettingsGateway,
    private val identity: () -> AccountIdentity?,
    private val scope: CoroutineScope,
) {
    private var active: AccountIdentity? = null
    private var generation = 0
    private var emailLoading = false
    private var stored by mutableStateOf(AccountSettingsState())
    val state: AccountSettingsState get() {
        // Always subscribe Compose to changes, even before identity activation.
        val snapshot = stored
        return if (active != null && active == identity()) snapshot else AccountSettingsState()
    }

    fun reconcile() {
        if (active == identity()) return
        active = identity(); generation++
        emailLoading = false
        stored = AccountSettingsState()
    }
    private fun current(who: AccountIdentity, version: Int) = active == who && identity() == who && generation == version

    fun loadEmail() {
        reconcile()
        val who = active ?: return
        if (emailLoading) return
        emailLoading = true
        val version = generation
        scope.launch {
            try {
                if (!current(who, version)) return@launch
                val email = gateway.email(who.owner)
                if (current(who, version)) stored = stored.copy(email = email?.takeIf(String::isNotBlank))
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) {
                if (current(who, version)) stored = stored.copy(email = null)
            } finally { if (current(who, version)) emailLoading = false }
        }
    }
    fun openDeletion() {
        reconcile()
        if (active == null) return
        stored = stored.copy(dialog = true)
        checkStatus()
    }
    fun dismiss() {
        if (!state.busy && !state.protected) stored = stored.copy(dialog = false, consequence = null, error = null)
    }
    fun checkStatus() = run(false)
    fun confirm() {
        if (!state.dialog || state.consequence == null || state.protected || state.phase != "not_requested") return
        run(true)
    }
    private fun run(confirm: Boolean) {
        reconcile()
        val who = active ?: return
        if (stored.busy) return
        val version = generation
        stored = stored.copy(busy = true, error = null,
            uncertain = stored.uncertain || confirm)
        scope.launch {
            try {
                if (!current(who, version)) return@launch
                val phase = gateway.request(who.owner, if (confirm) "POST" else "GET").getString("status")
                check(phase in setOf("not_requested", "draining", "auth_pending", "completed"))
                check(!confirm || phase != "not_requested")
                if (!current(who, version)) return@launch
                // A status read cannot disprove a timed-out POST that is still in flight.
                stored = stored.copy(phase = phase,
                    uncertain = stored.protected && phase == "not_requested", consequence = null)
                if (phase == "not_requested" && !stored.uncertain) {
                    val consequence = gateway.request(who.owner, "GET", preview = true).getString("consequence")
                    check(consequence in setOf("personal", "management_transferred", "family_deleted"))
                    if (current(who, version)) stored = stored.copy(consequence = consequence)
                }
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) {
                if (current(who, version)) stored = stored.copy(error =
                    "לא הצלחנו לבדוק את מצב החשבון. נסו שוב. ניתן גם לסגור ולהתנתק.")
            } finally {
                if (current(who, version)) stored = stored.copy(busy = false)
            }
        }
    }
}

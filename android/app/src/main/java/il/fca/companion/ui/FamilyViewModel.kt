package il.fca.companion.ui

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import il.fca.companion.net.*
import kotlinx.coroutines.*

internal data class FamilyIdentity(val owner: String, val family: Long)
internal enum class AddressStage { VIEW, EDIT, VERIFYING, CONFIRM, SAVING }
internal data class FamilyState(
    val memberAddition: Boolean = false,
    val profile: FamilyProfile? = null, val loading: Boolean = true, val loadError: Boolean = false,
    val rolePending: Set<String> = emptySet(), val roleErrors: Set<String> = emptySet(),
    val addressStage: AddressStage = AddressStage.VIEW, val draft: String = "", val candidate: ResolvedAddress? = null,
    val addressError: String? = null, val codeConfirmation: Boolean = false,
    val codePending: Boolean = false, val codeError: Boolean = false,
) {
    val addressBusy get() = addressStage == AddressStage.VERIFYING || addressStage == AddressStage.SAVING
}

/** Screen-local confirmed data and drafts only. Never persist family codes, addresses or confirmation tokens. */
internal class FamilyViewModel(private val api: FamilyGateway, private val identity: () -> FamilyIdentity?,
                               private val testScope: CoroutineScope? = null) : ViewModel() {
    var state by mutableStateOf(FamilyState()); private set
    private val scope get() = testScope ?: viewModelScope
    // visibleState reads this before DisposableEffect starts us. It must be observable
    // even when its guard short-circuits without reading state or identity().
    private var active by mutableStateOf<FamilyIdentity?>(null)
    private var generation = 0L
    private var root: Job? = null
    val visibleState get() = if (active != null && active == identity()) state else FamilyState()
    private fun current(who: FamilyIdentity, version: Long) = active == who && identity() == who && generation == version
    private fun launch(block: suspend () -> Unit) = CoroutineScope(scope.coroutineContext + checkNotNull(root)).launch { block() }
    private fun manager(): FamilyIdentity? = active?.takeIf {
        it == identity() && !state.loading && !state.loadError && root?.isActive == true && state.profile?.canManage == true
    }
    fun start() {
        val who = identity() ?: return
        if (active == who && root?.isActive == true) return
        if (active != who) stop()
        active = who; root = SupervisorJob(scope.coroutineContext[Job]); load()
    }
    fun stop() { generation++; root?.cancel(); root = null; active = null; state = FamilyState() }
    override fun onCleared() { stop() }
    fun reconcileIdentity() { if (active != null && active != identity()) stop() }
    fun pause() {
        val profile = visibleState.profile
        generation++; root?.cancel(); root = null
        state = FamilyState(profile = profile)
        if (active != identity()) stop()
    }
    fun openMemberAddition(): String? {
        if (state.loading || state.loadError || root?.isActive != true) return null
        val code = visibleState.profile?.code ?: return null
        if (state.memberAddition || state.codePending) return null
        state = state.copy(memberAddition = true)
        return code
    }
    fun closeMemberAddition() {
        if (!visibleState.memberAddition) return
        state = state.copy(memberAddition = false)
        if (!state.loading) load()
    }
    fun retry() { if (!state.loading && (state.profile == null || state.loadError)) load() }
    private fun load() {
        if (root?.isActive != true) return
        val who = active ?: return
        val version = generation
        state = state.copy(loading = true, loadError = false)
        launch {
            try {
                val data = api.profile(who.owner)
                if (current(who, version)) state = state.copy(profile = data, loading = false)
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) { if (current(who, version)) state = state.copy(loading = false, loadError = true) }
        }
    }
    fun role(ref: String, role: FamilyRole) {
        val who = manager() ?: return
        val member = state.profile?.members?.find { it.ref == ref } ?: return
        if (ref in state.rolePending || member.role == role) return
        val version = generation
        state = state.copy(rolePending = state.rolePending + ref, roleErrors = state.roleErrors - ref)
        launch {
            try {
                val updated = api.role(who.owner, ref, role)
                require(updated.ref == ref)
                if (current(who, version)) state = state.copy(profile = state.profile!!.let { p ->
                    p.copy(members = p.members.map { if (it.ref == ref) updated else it }) })
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) { if (current(who, version)) state = state.copy(roleErrors = state.roleErrors + ref) }
            finally { if (current(who, version)) state = state.copy(rolePending = state.rolePending - ref) }
        }
    }
    fun editAddress() {
        if (manager() == null || state.addressBusy) return
        state = state.copy(addressStage = AddressStage.EDIT, draft = state.profile!!.address, candidate = null, addressError = null)
    }
    fun draft(value: String) {
        if (manager() != null && state.addressStage == AddressStage.EDIT)
            state = state.copy(draft = value, candidate = null, addressError = null)
    }
    fun cancelAddress() {
        if (!state.addressBusy) state = state.copy(addressStage = AddressStage.VIEW, draft = "", candidate = null, addressError = null)
    }
    fun reviseAddress() {
        if (manager() != null && !state.addressBusy) state = state.copy(addressStage = AddressStage.EDIT, candidate = null, addressError = null)
    }
    fun verifyAddress() {
        val who = manager() ?: return
        if (state.addressStage != AddressStage.EDIT) return
        val draft = state.draft
        if (draft.isBlank() || draft.codePointCount(0, draft.length) > 200) {
            state = state.copy(addressError = "יש לכתוב כתובת בפורמט: עיר, רחוב, מספר בית, עד 200 תווים."); return
        }
        val version = generation
        state = state.copy(addressStage = AddressStage.VERIFYING, addressError = null)
        launch {
            try {
                val result = api.resolve(who.owner, draft)
                if (current(who, version)) state = state.copy(candidate = result, addressStage = AddressStage.CONFIRM)
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) { if (current(who, version)) state = state.copy(addressStage = AddressStage.EDIT,
                addressError = "לא ניתן לאמת את הכתובת. בדקו את הפרטים ונסו שוב.") }
        }
    }
    fun confirmAddress() {
        val who = manager() ?: return
        val candidate = state.candidate ?: return
        if (state.addressStage != AddressStage.CONFIRM) return
        val version = generation
        state = state.copy(addressStage = AddressStage.SAVING, addressError = null)
        launch {
            try {
                val address = api.address(who.owner, candidate)
                if (current(who, version)) state = state.copy(profile = state.profile!!.copy(address = address),
                    addressStage = AddressStage.VIEW, candidate = null, draft = "")
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) { if (current(who, version)) state = state.copy(addressStage = AddressStage.CONFIRM,
                addressError = "לא ניתן לאשר שהכתובת עודכנה. אפשר לנסות שוב או לחזור לעריכה ולבדוק מחדש.") }
        }
    }
    fun askRegenerate() { if (manager() != null && !state.codePending) state = state.copy(codeConfirmation = true, codeError = false) }
    fun cancelRegenerate() { if (!state.codePending) state = state.copy(codeConfirmation = false) }
    fun regenerate() {
        val who = manager() ?: return
        if (!state.codeConfirmation || state.codePending) return
        val version = generation
        state = state.copy(codePending = true, codeError = false)
        launch {
            try {
                val code = api.regenerate(who.owner)
                if (current(who, version)) state = state.copy(profile = state.profile!!.copy(code = code), codeConfirmation = false)
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) { if (current(who, version)) state = state.copy(codeError = true) }
            finally { if (current(who, version)) state = state.copy(codePending = false) }
        }
    }
}

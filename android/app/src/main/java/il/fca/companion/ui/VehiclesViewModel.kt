package il.fca.companion.ui

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import il.fca.companion.net.*
import java.util.UUID
import kotlinx.coroutines.*

internal data class VehiclesIdentity(val owner: String, val family: Long)
internal enum class VehiclesPage { LIST, ADD, PLACEHOLDER }
internal data class VehiclesState(
    val page: VehiclesPage = VehiclesPage.LIST, val rows: List<ManagedVehicle> = emptyList(),
    val selected: ManagedVehicle? = null, val loaded: Boolean = false, val loading: Boolean = false,
    val loadError: Boolean = false, val canCreate: Boolean = false,
    val draft: VehicleDraft = VehicleDraft(), val manufacturers: List<Manufacturer> = emptyList(),
    val catalogLoaded: Boolean = false, val catalogLoading: Boolean = false, val catalogError: Boolean = false,
    val submitting: Boolean = false, val submitError: String? = null, val pending: VehicleSubmission? = null
) {
    val active get() = rows.filter { !it.readOnly }
    val retired get() = rows.filter { it.readOnly }
    val matchingManufacturers get() = manufacturers.filter { it.name.contains(draft.manufacturerQuery, ignoreCase = true) }
}

/** Owner/family-scoped, memory-only flow. Retries never replace a submitted payload or UUID. */
internal class VehiclesViewModel(private val api: VehiclesGateway, private val identity: () -> VehiclesIdentity?,
    private val testScope: CoroutineScope? = null) : ViewModel() {
    var state by mutableStateOf(VehiclesState()); private set
    private val scope get() = testScope ?: viewModelScope
    private var active: VehiclesIdentity? = null
    private var epoch = 0L
    private var root: Job? = null
    private var submissionJob: Job? = null
    private fun valid(owner: VehiclesIdentity, version: Long) = active == owner && identity() == owner && epoch == version
    internal fun currentIdentity(): VehiclesIdentity? = identity()?.takeIf { it == active }
    private fun launch(block: suspend CoroutineScope.() -> Unit) =
        CoroutineScope(scope.coroutineContext + checkNotNull(root)).launch(block = block)
    fun start() {
        val next = identity()
        if (root?.isActive == true && active == next) return
        stop()
        if (next == null) return
        active = next; root = SupervisorJob(scope.coroutineContext[Job]); refresh()
    }
    fun stop() {
        epoch++; root?.cancel(); root = null; active = null; submissionJob = null; state = VehiclesState()
    }
    override fun onCleared() { stop() }
    fun refresh() {
        val owner = active ?: return
        if (state.loading) return
        val version = epoch
        state = state.copy(loading = true, loadError = false, canCreate = false)
        launch {
            try {
                val rows = api.vehicles(owner.owner)
                val canCreate = api.canCreate(owner.owner)
                if (valid(owner, version)) state = state.copy(rows = rows, loaded = true, loading = false, canCreate = canCreate)
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) { if (valid(owner, version)) state = state.copy(loading = false, loadError = true) }
        }
    }
    fun add() {
        if (!state.canCreate || state.page != VehiclesPage.LIST || identity() != active) return
        state = state.copy(page = VehiclesPage.ADD, draft = VehicleDraft(), pending = null, submitError = null)
        loadManufacturers()
    }
    fun select(vehicle: ManagedVehicle) {
        if (state.page == VehiclesPage.LIST && vehicle in state.rows)
            state = state.copy(page = VehiclesPage.PLACEHOLDER, selected = vehicle)
    }
    /** Returns false only when the shell should navigate from the list to Dashboard. */
    fun back(): Boolean {
        if (state.page == VehiclesPage.LIST) return false
        submissionJob?.cancel(); submissionJob = null
        state = state.copy(page = VehiclesPage.LIST, selected = null, draft = VehicleDraft(),
            pending = null, submitting = false, submitError = null)
        // A cancelled HTTP operation may still commit remotely. Reconcile the list, never resubmit.
        refresh()
        return true
    }
    fun edit(draft: VehicleDraft) {
        if (state.page != VehiclesPage.ADD || state.pending != null || state.submitting) return
        state = state.copy(draft = draft, submitError = null)
    }
    fun queryManufacturer(query: String) = edit(state.draft.copy(manufacturerQuery = query, manufacturer = null))
    fun chooseManufacturer(value: Manufacturer) {
        if (value in state.manufacturers) edit(state.draft.copy(manufacturer = value, manufacturerQuery = value.name))
    }
    fun loadManufacturers() {
        val owner = active ?: return
        if (state.catalogLoaded || state.catalogLoading) return
        val version = epoch
        state = state.copy(catalogLoading = true, catalogError = false)
        launch {
            try {
                val rows = api.manufacturers(owner.owner)
                if (valid(owner, version)) state = state.copy(manufacturers = rows, catalogLoaded = true, catalogLoading = false)
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) { if (valid(owner, version)) state = state.copy(catalogLoading = false, catalogError = true) }
        }
    }
    fun submit() {
        val owner = active ?: return
        if (identity() != owner || state.page != VehiclesPage.ADD || state.submitting || !state.canCreate || !state.draft.valid) return
        val request = state.pending ?: VehicleSubmission(UUID.randomUUID().toString(), state.draft)
        val version = epoch
        state = state.copy(pending = request, submitting = true, submitError = null)
        submissionJob = launch {
            try {
                api.create(owner.owner, request)
                if (!valid(owner, version) || state.pending !== request) return@launch
                state = state.copy(page = VehiclesPage.LIST, draft = VehicleDraft(), pending = null, submitting = false)
                refresh()
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                if (valid(owner, version) && state.pending === request) state = state.copy(submitting = false,
                    submitError = if (e is HttpFailure && e.status == 403) "אין הרשאה להוספת רכב"
                        else "לא ניתן לאשר את הוספת הרכב. נסו שוב עם אותם הפרטים.")
            }
        }
    }
}

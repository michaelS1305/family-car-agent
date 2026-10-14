package il.fca.companion.ui

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import il.fca.companion.net.*
import java.time.LocalDate
import kotlinx.coroutines.*

internal enum class VehicleDialog { EDIT, MAINTENANCE, RETIRE }
internal data class VehicleDetailsState(
    val detail: VehicleDetail? = null, val loading: Boolean = false, val error: Boolean = false,
    val admin: Boolean = false, val maintenance: List<VehicleMaintenance> = emptyList(),
    val maintenanceLoading: Boolean = false, val maintenanceError: Boolean = false,
    val dialog: VehicleDialog? = null, val busy: Boolean = false, val operationError: String? = null,
    val draft: VehicleDraft = VehicleDraft(), val catalog: List<Manufacturer> = emptyList(),
    val catalogLoaded: Boolean = false, val catalogLoading: Boolean = false, val catalogError: Boolean = false,
    val description: String = "", val date: LocalDate = LocalDate.now(),
    val maintenanceRef: String? = null, val confirmDelete: Boolean = false
) {
    val canManage get() = admin && detail != null && !detail.vehicle.readOnly && !loading && !error
    val matches get() = catalog.filter { it.name.contains(draft.manufacturerQuery, true) }
}

/** Per owner/family/vehicle presentation only; no local optimistic mutation or automatic POST retry. */
internal class VehicleDetailsViewModel(private val api: VehicleDetailsGateway, private val ref: String,
    private val identity: () -> VehiclesIdentity?, private val testScope: CoroutineScope? = null) : ViewModel() {
    var state by mutableStateOf(VehicleDetailsState()); private set
    private val scope get() = testScope ?: viewModelScope
    private var owner: VehiclesIdentity? = null
    private var generation = 0L
    private var root: Job? = null
    private var maintenanceRevision = 0L
    private fun valid(who: VehiclesIdentity, version: Long) = owner == who && identity() == who && generation == version
    private fun launch(block: suspend CoroutineScope.() -> Unit) =
        CoroutineScope(scope.coroutineContext + checkNotNull(root)).launch(block = block)
    fun start() {
        val next = identity() ?: return
        if (owner == next && root?.isActive == true) return
        stop(); owner = next; root = SupervisorJob(scope.coroutineContext[Job]); refresh(); refreshMaintenance()
    }
    fun stop() { generation++; root?.cancel(); root = null; owner = null; state = VehicleDetailsState() }
    override fun onCleared() { stop() }
    fun refresh() {
        val who = owner ?: return
        if (state.loading || state.busy) return
        val version = generation
        state = state.copy(loading = true, error = false, admin = false)
        launch {
            try {
                val detail = api.detail(who.owner, ref)
                val admin = api.canManage(who.owner)
                if (valid(who, version)) state = state.copy(detail = detail, admin = admin, loading = false,
                    dialog = if (detail.vehicle.readOnly) null else state.dialog)
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) { if (valid(who, version)) state = state.copy(loading = false, error = true) }
        }
    }
    fun refreshMaintenance() {
        val who = owner ?: return
        if (state.maintenanceLoading) return
        val version = generation
        val request = ++maintenanceRevision
        state = state.copy(maintenanceLoading = true, maintenanceError = false)
        launch {
            try {
                val rows = api.maintenance(who.owner, ref)
                if (valid(who, version) && request == maintenanceRevision) state = state.copy(maintenance = rows, maintenanceLoading = false)
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) { if (valid(who, version) && request == maintenanceRevision) state = state.copy(maintenanceLoading = false, maintenanceError = true) }
        }
    }
    fun open(dialog: VehicleDialog) {
        if (!state.canManage || state.busy || identity() != owner) return
        val v = state.detail!!.vehicle
        val maker = v.manufacturerId?.let { id -> v.manufacturerName?.let { Manufacturer(id, it) } }
        state = state.copy(dialog = dialog, operationError = null, description = "", date = LocalDate.now(),
            maintenanceRef = null, confirmDelete = false,
            draft = VehicleDraft(v.name, v.category, maker, maker?.name.orEmpty(), v.model.orEmpty(), v.plate.orEmpty()))
        if (dialog == VehicleDialog.EDIT) loadCatalog()
    }
    fun openMaintenance(item: VehicleMaintenance) {
        if (!state.canManage || state.busy || identity() != owner || item !in state.maintenance) return
        open(VehicleDialog.MAINTENANCE)
        state = state.copy(maintenanceRef = item.ref, description = item.description, date = item.date)
    }
    fun requestDelete() {
        if (state.canManage && !state.busy && identity() == owner &&
            state.dialog == VehicleDialog.MAINTENANCE && state.maintenanceRef != null)
            state = state.copy(confirmDelete = true, operationError = null)
    }
    fun cancelDelete() { if (!state.busy) state = state.copy(confirmDelete = false) }
    fun close() { if (!state.busy) state = state.copy(dialog = null, operationError = null, confirmDelete = false) }
    fun edit(draft: VehicleDraft) { if (!state.busy) state = state.copy(draft = draft, operationError = null) }
    fun query(query: String) = edit(state.draft.copy(manufacturerQuery = query, manufacturer = null))
    fun choose(maker: Manufacturer) { if (maker in state.catalog) edit(state.draft.copy(manufacturer = maker, manufacturerQuery = maker.name)) }
    fun maintenanceDraft(description: String, date: LocalDate) {
        if (!state.busy) state = state.copy(description = description, date = date, operationError = null)
    }
    fun loadCatalog() {
        val who = owner ?: return
        if (state.catalogLoaded || state.catalogLoading) return
        val version = generation
        state = state.copy(catalogLoading = true, catalogError = false)
        launch {
            try {
                val rows = api.manufacturers(who.owner)
                if (valid(who, version)) state = state.copy(catalog = rows, catalogLoaded = true, catalogLoading = false)
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) { if (valid(who, version)) state = state.copy(catalogLoading = false, catalogError = true) }
        }
    }
    fun submit() {
        val who = owner ?: return
        val dialog = state.dialog ?: return
        if (!state.canManage || state.busy || identity() != who) return
        val draft = state.draft
        if (dialog == VehicleDialog.EDIT && (!draft.valid || draft.manufacturer !in state.catalog)) return
        val description = state.description
        val date = state.date
        val item = state.maintenanceRef
        val deleting = dialog == VehicleDialog.MAINTENANCE && state.confirmDelete && item != null
        if (dialog == VehicleDialog.MAINTENANCE && !deleting && description.isBlank()) return
        val version = generation
        state = state.copy(busy = true, operationError = null)
        launch {
            try {
                when (dialog) {
                    VehicleDialog.EDIT -> api.edit(who.owner, ref, draft)
                    VehicleDialog.RETIRE -> api.retire(who.owner, ref)
                    VehicleDialog.MAINTENANCE -> when {
                        deleting -> api.deleteMaintenance(who.owner, ref, checkNotNull(item))
                        item != null -> api.updateMaintenance(who.owner, ref, item, description, date)
                        else -> api.addMaintenance(who.owner, ref, description, date)
                    }
                }
                if (!valid(who, version)) return@launch
                maintenanceRevision++
                state = state.copy(busy = false, dialog = null, maintenanceLoading = false, confirmDelete = false)
                refresh(); refreshMaintenance()
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                if (valid(who, version)) {
                    state = state.copy(busy = false, operationError = when {
                        e is HttpFailure && e.status == 403 -> "אין הרשאה לביצוע הפעולה"
                        dialog == VehicleDialog.RETIRE && e is HttpFailure && e.status == 409 -> "לא ניתן להוציא את הרכב משימוש כעת. ייתכן שהוא בשימוש."
                        dialog == VehicleDialog.MAINTENANCE && item != null -> "לא ניתן לאשר שהשינוי נשמר. בדקו את רשימת הטיפולים לפני ניסיון נוסף."
                        dialog == VehicleDialog.MAINTENANCE -> "לא ניתן לאשר שהטיפול נוסף. לפני ניסיון נוסף בדקו את רשימת הטיפולים."
                        else -> "הפעולה לא הושלמה. נסו שוב."
                    })
                    if (dialog == VehicleDialog.MAINTENANCE) {
                        maintenanceRevision++
                        state = state.copy(maintenanceLoading = false)
                        refreshMaintenance()
                    }
                }
            }
        }
    }
}

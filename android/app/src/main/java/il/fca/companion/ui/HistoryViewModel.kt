package il.fca.companion.ui

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import il.fca.companion.net.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.Flow

internal data class HistoryIdentity(val owner: String, val family: Long)
internal enum class CurrentUseStatus { LOADING, READY, UNAVAILABLE }
internal data class CurrentVehicleState(val status: CurrentUseStatus = CurrentUseStatus.LOADING,
    val vehicles: List<FamilyVehicle> = emptyList()) {
    val occupied get() = vehicles.filter { it.inUse }
    val allAvailable get() = status == CurrentUseStatus.READY && occupied.isEmpty()
}
internal data class HistoryState(
    val rows: List<HistoryUsage> = emptyList(), val loaded: Boolean = false,
    val loading: Boolean = false, val pageError: Boolean = false,
    val hasMore: Boolean = false, val nextCursor: String? = null,
    val applied: HistoryFilters = HistoryFilters(), val draft: HistoryFilters = HistoryFilters(),
    val sheet: Boolean = false, val rangeError: Boolean = false,
    val current: CurrentVehicleState = CurrentVehicleState(),
    val vehicleOptions: List<FamilyVehicle> = emptyList(), val members: List<HistoryMember> = emptyList(),
    val optionsLoading: Boolean = false, val optionsError: Boolean = false,
)

/** Memory-only screen lifetime. All mutations run on the main dispatcher; IO is in the gateway. */
internal class HistoryViewModel(
    private val gateway: HistoryGateway,
    private val identity: () -> HistoryIdentity?,
    private val broadcasts: (HistoryIdentity) -> Flow<BroadcastSignal>,
    private val testScope: CoroutineScope? = null,
) : ViewModel() {
    var state by mutableStateOf(HistoryState()); private set
    private val scope get() = testScope ?: viewModelScope
    private var active: HistoryIdentity? = null
    private var epoch = 0L
    private var filterEpoch = 0L
    private var currentEpoch = 0L
    private var root: Job? = null
    private var pageJob: Job? = null
    private var currentJob: Job? = null
    private var subscription: Job? = null
    private var optionsJob: Job? = null
    private var refreshPending = false
    private var connected: Boolean? = null
    private fun valid(expected: HistoryIdentity, version: Long) =
        active == expected && identity() == expected && epoch == version
    private fun launch(block: suspend CoroutineScope.() -> Unit): Job =
        CoroutineScope(scope.coroutineContext + checkNotNull(root)).launch(block = block)

    fun start() {
        val next = identity()
        if (root?.isActive == true && active == next) return
        stop()
        if (next == null) return
        active = next
        root = SupervisorJob(scope.coroutineContext[Job])
        state = HistoryState()
        loadPage(); refreshCurrent(); loadOptions(); subscribe()
    }
    fun stop() {
        epoch++; currentEpoch++; filterEpoch++
        root?.cancel(); root = null; active = null
        pageJob = null; currentJob = null; subscription = null; optionsJob = null
        refreshPending = false; connected = null
        state = HistoryState()
    }
    override fun onCleared() { stop() }

    fun openFilters() { state = state.copy(sheet = true, draft = state.applied, rangeError = false) }
    fun dismissFilters() { state = state.copy(sheet = false, draft = state.applied, rangeError = false) }
    fun editDraft(value: HistoryFilters) { state = state.copy(draft = value, rangeError = false) }
    fun applyFilters() {
        if (!state.draft.valid) { state = state.copy(rangeError = true); return }
        resetPages(state.draft)
        state = state.copy(sheet = false)
    }
    fun clearFilters() { resetPages(HistoryFilters()) }
    private fun resetPages(filters: HistoryFilters) {
        filterEpoch++; pageJob?.cancel(); pageJob = null
        state = state.copy(rows = emptyList(), loaded = false, loading = false, pageError = false,
            hasMore = false, nextCursor = null, applied = filters, draft = filters, rangeError = false)
        loadPage()
    }
    fun nextPage() {
        if (state.pageError || !state.loaded || !state.hasMore || state.nextCursor == null) return
        loadPage()
    }
    fun retryPage() { loadPage() }
    private fun loadPage() {
        val expected = active ?: return
        if (state.loading || (state.loaded && !state.hasMore)) return
        val version = epoch
        val filters = filterEpoch
        val query = state.applied
        val cursor = if (state.loaded) state.nextCursor ?: return else null
        state = state.copy(loading = true, pageError = false)
        pageJob = launch {
            try {
                val page = gateway.page(expected.owner, query, cursor)
                if (!valid(expected, version) || filters != filterEpoch) return@launch
                // A repeated cursor would make the end-of-list observer loop forever.
                check(!page.hasMore || (page.nextCursor != null && page.nextCursor != cursor))
                state = state.copy(rows = (state.rows + page.rows).distinctBy { it.sessionRef },
                    loaded = true, loading = false, hasMore = page.hasMore, nextCursor = page.nextCursor)
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) {
                if (valid(expected, version) && filters == filterEpoch)
                    state = state.copy(loading = false, pageError = true)
            }
        }
    }
    fun loadOptions() {
        val expected = active ?: return
        if (optionsJob?.isActive == true) return
        val version = epoch
        state = state.copy(optionsLoading = true, optionsError = false)
        optionsJob = launch {
            try {
                val members = gateway.members(expected.owner)
                if (valid(expected, version)) state = state.copy(members = members, optionsLoading = false)
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) {
                if (valid(expected, version)) state = state.copy(optionsLoading = false, optionsError = true)
            }
        }
    }
    fun retryCurrent() { subscribe(); refreshCurrent() }
    private fun subscribe() {
        val expected = active ?: return
        val version = epoch
        subscription?.cancel()
        connected = null
        subscription = launch {
            try {
                broadcasts(expected).collect { signal ->
                    if (!valid(expected, version)) return@collect
                    when (signal) {
                        BroadcastSignal.SUBSCRIBED -> { connected = true; refreshCurrent() }
                        BroadcastSignal.INVALIDATED -> refreshCurrent()
                        else -> {
                            connected = false; currentEpoch++
                            state = state.copy(current = state.current.copy(status = CurrentUseStatus.UNAVAILABLE))
                        }
                    }
                }
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) {
                if (valid(expected, version)) {
                    connected = false; currentEpoch++
                    state = state.copy(current = state.current.copy(status = CurrentUseStatus.UNAVAILABLE))
                }
            }
        }
    }
    fun refreshCurrent() {
        val expected = active ?: return
        if (currentJob?.isActive == true) { refreshPending = true; return }
        val version = epoch
        currentJob = launch {
            do {
                refreshPending = false
                val requestEpoch = currentEpoch
                state = state.copy(current = state.current.copy(status = CurrentUseStatus.LOADING))
                try {
                    val vehicles = gateway.vehicles(expected.owner)
                    if (!valid(expected, version)) return@launch
                    if (requestEpoch == currentEpoch) state = state.copy(vehicleOptions = vehicles,
                        current = CurrentVehicleState(if (connected == false) CurrentUseStatus.UNAVAILABLE
                            else CurrentUseStatus.READY, vehicles))
                } catch (e: CancellationException) { throw e }
                catch (_: Exception) {
                    if (!valid(expected, version)) return@launch
                    state = state.copy(current = state.current.copy(status = CurrentUseStatus.UNAVAILABLE))
                }
            } while (refreshPending && valid(expected, version))
        }
    }
}

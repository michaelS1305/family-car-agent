package il.fca.companion.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import il.fca.companion.net.*
import kotlinx.coroutines.*
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.YearMonth
import java.time.ZoneId

internal fun bookingMonthDays(month: YearMonth): List<LocalDate> {
    val first = month.atDay(1)
    val leading = first.dayOfWeek.value % 7
    val count = ((leading + month.lengthOfMonth() + 6) / 7) * 7
    val start = first.minusDays(leading.toLong())
    return List(count) { start.plusDays(it.toLong()) }
}

internal val BookingMonths = listOf("ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
    "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר")
internal val BookingWeekdays = listOf("ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת")
internal fun bookingDateLabel(date: LocalDate) =
    "יום ${BookingWeekdays[date.dayOfWeek.value % 7]}, ${date.dayOfMonth} ב${BookingMonths[date.monthValue - 1]} ${date.year}"

internal data class BookingIdentity(val owner: String, val family: Long)
internal data class BookingData(val requested: BookingRange? = null, val loaded: BookingRange? = null,
    val rows: List<BookingReservation> = emptyList(), val loading: Boolean = false,
    val refreshing: Boolean = false, val error: Boolean = false, val query: BookingQuery? = null)

internal class BookingViewModel(private val gateway: BookingGateway,
    private val currentIdentity: () -> BookingIdentity?, private val testScope: CoroutineScope? = null,
    private val vehicleLoad: suspend (String) -> List<ManagedVehicle> = { error("Vehicles unavailable") },
    private val now: () -> LocalDateTime = { LocalDateTime.now(ZoneId.of("Asia/Jerusalem")) },
    private val memberLoad: suspend (String) -> List<FamilyMember> = { error("Members unavailable") },
    private val today: () -> LocalDate = {
    LocalDate.now(ZoneId.of("Asia/Jerusalem"))
}) : ViewModel() {
    var selectedDate by mutableStateOf(today())
        private set
    var visibleMonth by mutableStateOf(YearMonth.from(selectedDate))
        private set
    var firstMonth by mutableStateOf(visibleMonth.minusYears(5))
        private set
    val pageCount = 121
    private var identity: Pair<Long, Long?>? = null
    private var active by mutableStateOf<BookingIdentity?>(null)
    private var data by mutableStateOf(BookingData())
    private var visible = false
    private var generation = 0L
    private var request: Job? = null
    private var action by mutableStateOf(BookingAction())
    private var mutationGeneration = 0L
    private var mutation: Job? = null
    private var vehicleGeneration = 0L
    private var vehicleRequest: Job? = null
    private var filters by mutableStateOf(BookingFilterState())
    private var catalogGeneration = 0L
    private var catalogRequest: Job? = null
    private var pending by mutableStateOf<BookingPending?>(null)
    var sheetExpanded by mutableStateOf(false)
        private set
    val visibleFilters get() = if (active != null && active == currentIdentity()) filters else BookingFilterState()
    val visiblePending get() = if (active != null && active == currentIdentity()) pending else null
    val query get() = BookingQuery(bookingRange(visibleMonth), visibleFilters.applied)
    val canAcknowledge get() = visiblePending?.readQuery == query && visiblePending?.inspected == true &&
        !visibleAction.submitting && !visibleData.loading && !visibleData.refreshing && !visibleData.error
    val visibleAction get() = if (active != null && active == currentIdentity()) action else BookingAction()
    private val scope get() = testScope ?: viewModelScope
    val visibleData: BookingData get() {
        if (active == null || active != currentIdentity()) return BookingData()
        val range = bookingRange(visibleMonth)
        return if (data.requested == range && data.query == query) data else BookingData()
    }

    fun activate(ownerGeneration: Long, familyId: Long?) {
        val next = ownerGeneration to familyId
        val who = currentIdentity()
        if (active == who && (identity == next || identity == null)) {
            identity = next
            return
        }
        identity = next
        invalidate()
        resetAction()
        clearFiltersAndPending()
        active = who
        data = BookingData()
        selectedDate = today()
        visibleMonth = YearMonth.from(selectedDate)
        firstMonth = visibleMonth.minusYears(5)
        if (visible) load()
    }

    fun enter() {
        if (visible && active == currentIdentity()) return
        visible = true
        sheetExpanded = false
        reconcileIdentity()
        load()
    }
    fun leave() {
        visible = false
        filters = filters.copy(open = false, draft = filters.applied, loading = false)
        catalogGeneration++; catalogRequest?.cancel()
        invalidate()
        val wasPending = pending != null
        resetAction()
        if (wasPending) {
            pending = pending?.copy(readQuery = null)
            action = BookingAction(reconciling = true, notice = "תוצאת הפעולה אינה ודאית. יש לבדוק את ההזמנות לפני ניסיון נוסף.")
        }
        data = data.copy(loading = false, refreshing = false)
        reconcileIdentity()
    }
    private fun invalidate() { generation++; request?.cancel(); request = null }
    private fun reconcileIdentity() {
        val who = currentIdentity()
        if (active == who) return
        invalidate(); resetAction(); clearFiltersAndPending(); active = who; data = BookingData()
        selectedDate = today(); visibleMonth = YearMonth.from(selectedDate)
        firstMonth = visibleMonth.minusYears(5)
    }
    fun retry() { if (visible) load() }
    private fun load() {
        if (!visible) return
        reconcileIdentity()
        val who = active ?: return
        val range = bookingRange(visibleMonth)
        val key = query
        if (data.query == key && (data.loading || data.refreshing)) return
        invalidate()
        val version = generation
        pending = pending?.copy(readQuery = null)
        if (key.effective == null) {
            data = BookingData(requested = range, loaded = range, query = key)
            return
        }
        val retain = data.loaded == range && data.query == key
        data = if (retain) data.copy(requested = range, refreshing = true, loading = false, error = false)
            else BookingData(requested = range, loading = true, query = key)
        request = scope.launch {
            try {
                val rows = gateway.reservations(who.owner, key)
                if (current(who, version, key)) {
                    data = BookingData(range, range, rows, query = key)
                    if (!action.submitting) pending = pending?.observe(key)
                }
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) {
                if (current(who, version, key)) data = data.copy(loading = false, refreshing = false, error = true)
            }
        }
    }
    private fun current(who: BookingIdentity, version: Long, key: BookingQuery) =
        visible && active == who && currentIdentity() == who && generation == version &&
            data.query == key && query == key
    override fun onCleared() { invalidate(); resetAction(); clearFiltersAndPending() }

    private fun clearFiltersAndPending() {
        catalogGeneration++; catalogRequest?.cancel(); catalogRequest = null
        filters = BookingFilterState(); pending = null; sheetExpanded = false
    }
    fun expandSheet(expanded: Boolean) { sheetExpanded = expanded }
    fun openFilters() {
        reconcileIdentity()
        if (!visible || active == null || action.submitting || action.draft != null || action.confirmation != null) return
        filters = filters.copy(open = true, draft = filters.applied, invalid = false)
        if (!filters.loaded) loadFilterChoices()
    }
    fun dismissFilters() { filters = filters.copy(open = false, draft = filters.applied, invalid = false) }
    fun editFilters(value: BookingFilters) { if (filters.open) filters = filters.copy(draft = value, invalid = false) }
    fun clearDraftFilters() = editFilters(BookingFilters())
    fun applyFilters() {
        reconcileIdentity()
        if (!filters.open) return
        if (!filters.draft.valid) { filters = filters.copy(invalid = true); return }
        val changed = filters.applied != filters.draft
        filters = filters.copy(applied = filters.draft, open = false, invalid = false)
        if (changed) load()
    }
    fun loadFilterChoices() {
        reconcileIdentity()
        val who = active ?: return
        if (!visible || filters.loading) return
        val version = ++catalogGeneration
        filters = filters.copy(loading = true, error = false)
        catalogRequest = scope.launch {
            try {
                val choices = coroutineScope {
                    val vehicles = async { vehicleLoad(who.owner) }
                    val members = async { memberLoad(who.owner) }
                    vehicles.await() to members.await()
                }
                if (visible && active == who && currentIdentity() == who && catalogGeneration == version)
                    filters = filters.copy(vehicles = choices.first, members = choices.second,
                        loaded = true, loading = false, error = false)
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) {
                if (active == who && currentIdentity() == who && catalogGeneration == version)
                    filters = filters.copy(loading = false, error = true)
            }
        }
    }
    fun acknowledgeUncertain() {
        reconcileIdentity()
        if (!visible || !canAcknowledge) return
        pending = null
        resetAction()
        action = BookingAction(notice = "אישרת להמשיך למרות אי־הוודאות. הפעולה לא נשלחה שוב.")
    }

    private fun resetAction() {
        mutationGeneration++; mutation?.cancel(); mutation = null
        vehicleGeneration++; vehicleRequest?.cancel(); vehicleRequest = null
        action = BookingAction()
    }
    private fun actionCurrent(who: BookingIdentity, version: Long) =
        visible && active == who && currentIdentity() == who && mutationGeneration == version
    private fun ready(): Boolean {
        reconcileIdentity()
        return visible && active != null && pending == null && !filters.open && !action.submitting && !action.uncertain && !action.reconciling
    }
    fun openCreate() {
        if (!ready()) return
        val date = maxOf(selectedDate, now().toLocalDate())
        resetAction()
        action = BookingAction(draft = BookingDraft(startDate = date, endDate = date))
        loadVehicles()
    }
    fun selectMode(mode: BookingSelection) {
        if (!ready()) return
        resetAction(); action = BookingAction(selection = mode)
        sheetExpanded = true
    }
    fun eligible(row: BookingReservation) = active == currentIdentity() && bookingEligible(row, now())
    fun startLocked() = visibleAction.draft?.original?.let { it.start < now() } == true
    fun choose(ref: String) {
        if (!ready()) return
        val row = visibleData.rows.singleOrNull { it.ref == ref } ?: return
        if (!eligible(row)) return
        when (action.selection) {
            BookingSelection.EDIT -> {
                action = action.copy(draft = BookingDraft(row, row.start.toLocalDate(), row.end.toLocalDate(),
                    row.start.toLocalTime(), row.end.toLocalTime()), error = null)
                loadVehicles()
            }
            BookingSelection.CANCEL -> action = action.copy(confirmation = row, error = null)
            else -> Unit
        }
    }
    // Returns true if local Back was consumed. Global identity invalidation bypasses this.
    fun dismiss(): Boolean {
        if (filters.open) { dismissFilters(); return true }
        if (action.submitting) return true
        if (action.uncertain) { reconcileOutcome(); return true }
        if (action.draft != null || action.confirmation != null) {
            vehicleGeneration++; vehicleRequest?.cancel()
            action = action.copy(draft = null, confirmation = null, error = null, vehiclesLoading = false)
            return true
        }
        if (action.selection != BookingSelection.NONE) { resetAction(); return true }
        if (sheetExpanded) { sheetExpanded = false; return true }
        return false
    }
    fun editDate(start: Boolean, date: LocalDate) {
        if (!ready() || (start && startLocked())) return
        val draft = action.draft ?: return
        // Date-only edits preserve the time (including seconds); explicit time edits reset seconds.
        action = action.copy(draft = if (start) draft.copy(startDate = date) else draft.copy(endDate = date), error = null)
    }
    fun editTime(start: Boolean, time: LocalTime) {
        if (!ready() || (start && startLocked())) return
        val draft = action.draft ?: return
        val minute = time.withSecond(0).withNano(0)
        action = action.copy(draft = if (start) draft.copy(startTime = minute) else draft.copy(endTime = minute), error = null)
    }
    fun chooseVehicle(ref: String?) {
        if (!ready() || !action.vehiclesLoaded || action.vehiclesLoading) return
        val draft = action.draft ?: return
        val preserved = draft.original != null && ref == draft.original.vehicleRef
        if (!preserved && action.vehicles.none { it.ref == ref && !it.readOnly }) return
        action = action.copy(draft = draft.copy(vehicleRef = ref), error = null)
    }
    fun loadVehicles() {
        if (!ready() || action.draft == null || action.vehiclesLoading) return
        val who = active ?: return
        val version = ++vehicleGeneration
        action = action.copy(vehiclesLoading = true, vehicleError = false)
        vehicleRequest = scope.launch {
            try {
                val vehicles = vehicleLoad(who.owner)
                if (visible && active == who && currentIdentity() == who && vehicleGeneration == version) {
                    var draft = action.draft ?: return@launch
                    val choices = vehicles.filterNot { it.readOnly }
                    if (draft.original == null) {
                        val chosen = draft.vehicleRef?.takeIf { ref -> choices.any { it.ref == ref } }
                        draft = draft.copy(vehicleRef = chosen ?: choices.singleOrNull()?.ref)
                    }
                    action = action.copy(draft = draft, vehicles = vehicles, vehiclesLoaded = true,
                        vehiclesLoading = false, vehicleError = false)
                }
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) {
                if (active == who && currentIdentity() == who && vehicleGeneration == version)
                    action = action.copy(vehiclesLoading = false, vehicleError = true)
            }
        }
    }
    fun submit() {
        if (!ready()) return
        val who = active ?: return
        val draft = action.draft
        val target = draft?.original ?: action.confirmation
        if (target != null && !eligible(target)) {
            action = action.copy(error = bookingRejection("RESERVATION_NOT_FOUND_OR_UNAVAILABLE")); return
        }
        if (draft == null && action.confirmation == null) return
        if (draft != null) {
            val start = draft.start; val end = draft.end; val clock = now()
            if (start == null || end == null || end <= start || end <= clock ||
                (start < clock && (target == null || start != target.start)) ||
                (target != null && target.start < clock && start != target.start)) {
                action = action.copy(error = "יש לבחור טווח שעות תקין שאינו בעבר."); return
            }
            val unchanged = target != null && draft.vehicleRef == target.vehicleRef
            val activeChoice = action.vehicles.any { it.ref == draft.vehicleRef && !it.readOnly }
            val generalCreate = target == null && draft.vehicleRef == null && action.vehicles.none { !it.readOnly }
            if (!action.vehiclesLoaded || action.vehiclesLoading || action.vehicleError || !(unchanged || activeChoice || generalCreate)) {
                action = action.copy(error = "יש לטעון את הרכבים ולבחור רכב זמין."); return
            }
        }
        invalidate()
        data = data.copy(loading = false, refreshing = false)
        val version = ++mutationGeneration
        pending = BookingPending(if (draft == null) BookingOperation.CANCEL else if (target == null)
            BookingOperation.CREATE else BookingOperation.EDIT, target?.ref,
            draft?.start ?: checkNotNull(target).start, draft?.end ?: checkNotNull(target).end,
            if (draft != null) draft.vehicleRef else target?.vehicleRef, target)
        action = action.copy(submitting = true, error = null, notice = null)
        mutation = scope.launch {
            try {
                val saved = if (draft == null) { gateway.cancel(who.owner, checkNotNull(target).ref); null }
                    else if (target == null) gateway.create(who.owner, draft.change())
                    else gateway.update(who.owner, target.ref, draft.change())
                if (!actionCurrent(who, version)) return@launch
                pending = null
                invalidate(); data = BookingData()
                val outside = saved != null && pageOf(YearMonth.from(saved.start)) !in 0 until pageCount
                action = BookingAction(notice = if (outside) "ההזמנה נשמרה. תאריך ההתחלה מחוץ לטווח לוח השנה."
                    else if (saved == null) "ההזמנה בוטלה." else "ההזמנה נשמרה.")
                if (saved != null && !outside) {
                    selectedDate = saved.start.toLocalDate(); visibleMonth = YearMonth.from(selectedDate)
                }
                if (saved != null && !filters.applied.matches(saved))
                    action = action.copy(notice = "ההזמנה נשמרה, אך אינה מוצגת תחת המסננים הנוכחיים.")
                load()
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                if (!actionCurrent(who, version)) return@launch
                val rejected = (e is BookingFailure && e.status in 400..499) ||
                    (e is HttpFailure && e.status in 400..499)
                if (rejected) pending = null
                else {
                    invalidate(); pending = pending?.copy(readQuery = null)
                    data = data.copy(loading = false, refreshing = false)
                }
                action = action.copy(submitting = false, uncertain = !rejected,
                    error = if (rejected) bookingRejection((e as? BookingFailure)?.code)
                    else "תוצאת הפעולה אינה ודאית. יש לרענן ולבדוק את ההזמנות לפני ניסיון נוסף.")
                if (rejected && data.loaded != bookingRange(visibleMonth)) load()
                // Never trust optional error-body vehicle choices; reload the authenticated catalog instead.
                if (e is BookingFailure && e.code in setOf("VEHICLE_REQUIRED", "VEHICLE_NOT_FOUND_OR_UNAVAILABLE")) loadVehicles()
            }
        }
    }
    fun reconcileOutcome() {
        if (action.submitting || active != currentIdentity()) return
        val date = pending?.start?.toLocalDate() ?: return
        val outside = pageOf(YearMonth.from(date)) !in 0 until pageCount
        val notice = "תוצאת הפעולה אינה ודאית. בדקו את ההזמנות לפני יצירה או שינוי נוסף." +
            if (outside) " התאריך שנבחר מחוץ לטווח לוח השנה." else ""
        resetAction(); action = BookingAction(reconciling = true, notice = notice)
        sheetExpanded = true
        if (!outside) { selectedDate = date; visibleMonth = YearMonth.from(date) }
        invalidate(); data = BookingData(); load()
    }

    fun monthAt(page: Int): YearMonth = firstMonth.plusMonths(page.toLong())
    fun pageOf(month: YearMonth): Int = java.time.temporal.ChronoUnit.MONTHS.between(firstMonth, month).toInt()
    fun selectDate(date: LocalDate) {
        val month = YearMonth.from(date)
        if (pageOf(month) !in 0 until pageCount) return
        selectedDate = date
        visibleMonth = month
        if (data.requested != bookingRange(month)) load()
    }
    fun moveToMonth(month: YearMonth) {
        if (pageOf(month) !in 0 until pageCount) return
        visibleMonth = month
        selectedDate = month.atDay(selectedDate.dayOfMonth.coerceAtMost(month.lengthOfMonth()))
        if (data.requested != bookingRange(month)) load()
    }
    fun previousMonth() = moveToMonth(visibleMonth.minusMonths(1))
    fun nextMonth() = moveToMonth(visibleMonth.plusMonths(1))
}

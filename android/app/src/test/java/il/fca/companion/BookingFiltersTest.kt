package il.fca.companion

import android.app.Application
import il.fca.companion.net.*
import il.fca.companion.ui.*
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.IOException
import java.net.URLDecoder
import java.time.*

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class BookingFiltersTest {
    private val day = LocalDate.of(2026, 10, 15)
    private fun ref(n: Int) = "00000000-0000-0000-0000-%012d".format(n)
    private fun row(n: Int = 1, vehicle: String? = ref(10), member: String = ref(20)) =
        BookingReservation(ref(n), "שם", member, day.atTime(12, 0), day.atTime(14, 0), true, vehicle, "רכב", VehicleCategory.SEDAN)
    private fun vehicle(retired: Boolean = false) = ManagedVehicle(ref(10), "רכב", Instant.EPOCH,
        if (retired) Instant.EPOCH else null, VehicleCategory.SEDAN, null, null, null, null)
    private class Api : BookingGateway {
        val reads = mutableListOf<BookingQuery>()
        var writes = 0
        var rows = emptyList<BookingReservation>()
        var failWrite = false
        var response: suspend (BookingQuery) -> List<BookingReservation> = { key -> rows.filter(key.filters::matches) }
        override suspend fun reservations(owner: String, range: BookingRange): List<BookingReservation> = error("Use precise query")
        override suspend fun reservations(owner: String, query: BookingQuery): List<BookingReservation> {
            reads += query; return response(query)
        }
        override suspend fun create(owner: String, change: BookingChange): BookingReservation {
            writes++; if (failWrite) throw IOException()
            return BookingReservation("00000000-0000-0000-0000-000000000001", "שם",
                "00000000-0000-0000-0000-000000000020", change.start, change.end, true,
                change.vehicleRef, null, null).also { rows = rows + it }
        }
        override suspend fun update(owner: String, ref: String, change: BookingChange): BookingReservation {
            writes++; if (failWrite) throw IOException()
            return rows.single { it.ref == ref }.copy(start = change.start, end = change.end,
                vehicleRef = change.vehicleRef).also { saved -> rows = rows.map { if (it.ref == ref) saved else it } }
        }
        override suspend fun cancel(owner: String, ref: String) {
            writes++; if (failWrite) throw IOException()
            rows = rows.filterNot { it.ref == ref }
        }
    }
    private fun model(api: Api, scope: CoroutineScope, identity: () -> BookingIdentity? = { BookingIdentity("A", 1) },
        vehicles: suspend (String) -> List<ManagedVehicle> = { listOf(vehicle()) },
        members: suspend (String) -> List<FamilyMember> = { listOf(FamilyMember(ref(20), "שם", FamilyRole.NONE, false)) }) =
        BookingViewModel(api, identity, scope, vehicleLoad = vehicles, memberLoad = members,
            now = { day.atTime(10, 0) }, today = { day })
    private suspend fun settle() { repeat(12) { yield() } }
    private fun apply(vm: BookingViewModel, filters: BookingFilters) {
        vm.openFilters(); vm.editFilters(filters); vm.applyFilters()
    }
    private suspend fun create(vm: BookingViewModel) {
        vm.openCreate(); settle()
        vm.editTime(true, LocalTime.NOON); vm.editTime(false, LocalTime.of(14, 0))
        vm.submit(); settle()
    }

    @Test fun precisePublicParametersAndAndSemantics() {
        val filters = BookingFilters(ref(10), ref(20), day.atTime(11, 31), day.atTime(15, 42))
        val path = URLDecoder.decode(BookingApi.path(BookingQuery(bookingRange(YearMonth.from(day)), filters)), "UTF-8")
        assertTrue(path.contains("range_start=2026-10-15T11:31:00"))
        assertTrue(path.contains("range_end=2026-10-15T15:42:00"))
        assertTrue(path.contains("vehicle_ref=${ref(10)}")); assertTrue(path.contains("member_ref=${ref(20)}"))
        assertTrue(path.contains("scope=all")); assertFalse(path.contains("family")); assertFalse(path.contains("time="))
        assertTrue(filters.matches(row()))
        assertFalse(filters.matches(row(vehicle = null)))
        assertFalse(filters.matches(row(member = ref(21))))
        assertTrue(BookingFilters().matches(row(vehicle = null)))
    }
    @Test fun optionalBoundsInvalidRangesAndGridIntersection() {
        val grid = bookingRange(YearMonth.from(day))
        assertEquals(grid.start.atStartOfDay(), BookingQuery(grid).effective?.start)
        assertEquals(grid.endExclusive.atStartOfDay(), BookingQuery(grid).effective?.end)
        assertEquals(day.atTime(9, 12), BookingQuery(grid, BookingFilters(start = day.atTime(9, 12))).effective?.start)
        assertEquals(day.atTime(18, 34), BookingQuery(grid, BookingFilters(end = day.atTime(18, 34))).effective?.end)
        assertFalse(BookingFilters(start = day.atStartOfDay(), end = day.atStartOfDay()).valid)
        assertFalse(BookingFilters(start = day.plusDays(1).atStartOfDay(), end = day.atStartOfDay()).valid)
        assertNull(BookingQuery(grid, BookingFilters(start = grid.endExclusive.atStartOfDay())).effective)
    }
    @Test fun projectionUsesTripleIntersectionMidnightActualEndpointsAndSorting() {
        val overnight = row().copy(start = day.minusDays(1).atTime(22, 0), end = day.atTime(8, 0))
        val query = BookingQuery(bookingRange(YearMonth.from(day)), BookingFilters(start = day.atStartOfDay()))
        assertEquals(setOf(day), bookingDots(listOf(overnight), query))
        assertTrue(bookingRows(listOf(overnight), day.minusDays(1), query).isEmpty())
        assertEquals(overnight, bookingRows(listOf(overnight), day, query).single())
        assertFalse(day.plusDays(1) in bookingDots(listOf(row().copy(end = day.plusDays(1).atStartOfDay())), query))
        assertEquals(listOf(row(), overnight), bookingRows(listOf(overnight, row()), day, query))
    }
    @Test fun dstAndAllGridSizesStayWallClock() {
        listOf(YearMonth.of(2026, 2), YearMonth.of(2026, 3), YearMonth.of(2026, 10)).forEach { month ->
            val grid = bookingRange(month)
            val effective = checkNotNull(BookingQuery(grid).effective)
            assertEquals(Duration.ofDays(bookingMonthDays(month).size.toLong()), Duration.between(effective.start, effective.end))
            assertTrue(Duration.between(effective.start, effective.end) <= Duration.ofDays(42))
        }
    }
    @Test fun draftCancelClearAndInvalidApplyDoNotFetch() = runBlocking {
        val api = Api(); val vm = model(api, this); vm.enter(); settle()
        vm.openFilters(); vm.editFilters(BookingFilters(vehicleRef = ref(10))); settle()
        assertEquals(1, api.reads.size); vm.dismissFilters(); assertEquals(BookingFilters(), vm.visibleFilters.applied)
        apply(vm, BookingFilters(vehicleRef = ref(10))); settle(); assertEquals(2, api.reads.size)
        vm.openFilters(); vm.clearDraftFilters(); assertEquals(ref(10), vm.visibleFilters.applied.vehicleRef)
        vm.dismissFilters(); assertEquals(ref(10), vm.visibleFilters.draft.vehicleRef)
        vm.openFilters(); vm.clearDraftFilters(); vm.applyFilters(); settle(); assertEquals(3, api.reads.size)
        apply(vm, BookingFilters(start = day.atStartOfDay(), end = day.atStartOfDay()))
        assertTrue(vm.visibleFilters.invalid); assertTrue(vm.visibleFilters.open); assertEquals(3, api.reads.size)
    }
    @Test fun emptyIntersectionMakesNoReadAndClearsPresentation() = runBlocking {
        val api = Api().apply { rows = listOf(row()) }; val vm = model(api, this); vm.enter(); settle()
        apply(vm, BookingFilters(start = day.plusYears(1).atStartOfDay())); settle()
        assertEquals(1, api.reads.size); assertTrue(vm.visibleData.rows.isEmpty())
        assertFalse(vm.visibleData.loading); assertFalse(vm.visibleData.error); assertNotNull(vm.visibleData.loaded)
    }
    @Test fun rapidABAChangesIgnoreOldRepliesAndDeduplicateRetry() = runBlocking {
        val api = Api(); val vm = model(api, this); vm.enter(); settle()
        val old = CompletableDeferred<List<BookingReservation>>()
        api.response = { withContext(NonCancellable) { old.await() } }
        apply(vm, BookingFilters(vehicleRef = ref(10))); settle(); vm.retry(); settle(); assertEquals(2, api.reads.size)
        api.response = { emptyList() }
        apply(vm, BookingFilters(memberRef = ref(20))); settle()
        apply(vm, BookingFilters(vehicleRef = ref(10))); settle()
        old.complete(listOf(row())); settle(); assertTrue(vm.visibleData.rows.isEmpty())
    }
    @Test fun sameQueryRefreshFailureRetainsDataNotFakeEmpty() = runBlocking {
        val api = Api().apply { rows = listOf(row()) }; val vm = model(api, this); vm.enter(); settle()
        apply(vm, BookingFilters(vehicleRef = ref(10))); settle()
        api.response = { throw IOException() }; vm.retry(); settle()
        assertTrue(vm.visibleData.error); assertEquals(1, vm.visibleData.rows.size)
        apply(vm, BookingFilters(memberRef = ref(21))); settle()
        assertTrue(vm.visibleData.error); assertTrue(vm.visibleData.rows.isEmpty()); assertNull(vm.visibleData.loaded)
    }
    @Test fun retiredCatalogIndependentFromEditorAndIdentityInvalidatesLateCatalog() = runBlocking {
        var identity = BookingIdentity("A", 1)
        val late = CompletableDeferred<List<ManagedVehicle>>()
        var calls = 0
        val vm = model(Api(), this, { identity }, { calls++; withContext(NonCancellable) { late.await() } })
        vm.enter(); settle(); vm.openFilters(); vm.loadFilterChoices(); settle(); assertEquals(1, calls)
        identity = BookingIdentity("A", 2); assertTrue(vm.visibleFilters.vehicles.isEmpty()); vm.activate(1, 2)
        late.complete(listOf(vehicle(true))); settle(); assertTrue(vm.visibleFilters.vehicles.isEmpty())
        assertEquals(BookingFilters(), vm.visibleFilters.applied)
        vm.openFilters(); settle(); assertTrue(vm.visibleFilters.vehicles.single().readOnly)
        vm.dismissFilters(); vm.openCreate(); settle(); assertNull(vm.visibleAction.draft?.vehicleRef)
    }
    @Test fun catalogFailureRetainsAppliedSelectionAndCanRetry() = runBlocking {
        var fail = true
        val vm = model(Api(), this, members = { if (fail) throw IOException() else emptyList() })
        vm.enter(); settle(); apply(vm, BookingFilters(memberRef = ref(20))); settle()
        vm.openFilters(); settle(); assertTrue(vm.visibleFilters.error)
        assertEquals(ref(20), vm.visibleFilters.applied.memberRef)
        fail = false; vm.loadFilterChoices(); settle(); assertTrue(vm.visibleFilters.loaded)
    }
    @Test fun filtersSurviveCreateAndMonthAndDoNotPreselectEditorVehicle() = runBlocking {
        val api = Api(); val vm = model(api, this); vm.enter(); settle()
        val filters = BookingFilters(vehicleRef = ref(11))
        apply(vm, filters); settle(); create(vm)
        assertEquals(filters, vm.visibleFilters.applied); assertEquals(1, api.writes)
        assertEquals(ref(10), api.rows.single().vehicleRef)
        assertTrue(checkNotNull(vm.visibleAction.notice).contains("אינה מוצגת"))
        assertTrue(vm.visibleData.rows.isEmpty())
        vm.nextMonth(); settle(); assertEquals(filters, api.reads.last().filters)
    }
    @Test fun editAcrossMonthAndCancelKeepFilters() = runBlocking {
        val api = Api().apply { rows = listOf(row()) }; val vm = model(api, this); vm.enter(); settle()
        val filters = BookingFilters(vehicleRef = ref(10)); apply(vm, filters); settle()
        vm.selectMode(BookingSelection.EDIT); vm.choose(ref(1)); settle()
        vm.editDate(true, day.plusMonths(1)); vm.editDate(false, day.plusMonths(1)); vm.submit(); settle()
        assertEquals(day.plusMonths(1), vm.selectedDate); assertEquals(filters, vm.visibleFilters.applied)
        vm.selectMode(BookingSelection.CANCEL); vm.choose(ref(1)); vm.submit(); settle()
        assertEquals(2, api.writes); assertTrue(vm.visibleData.rows.isEmpty()); assertEquals(filters, vm.visibleFilters.applied)
    }
    @Test fun uncertainCreateHasNoRefRequiresRelevantReadAndExplicitAcknowledgement() = runBlocking {
        val api = Api().apply { failWrite = true }; val vm = model(api, this); vm.enter(); settle(); create(vm)
        assertEquals(BookingOperation.CREATE, vm.visiblePending?.operation); assertNull(vm.visiblePending?.ref)
        vm.acknowledgeUncertain(); assertNotNull(vm.visiblePending)
        vm.reconcileOutcome(); settle(); assertTrue(vm.canAcknowledge); assertTrue(vm.visibleAction.reconciling)
        vm.openCreate(); assertNull(vm.visibleAction.draft)
        vm.acknowledgeUncertain(); assertNull(vm.visiblePending); assertEquals(1, api.writes)
        vm.openCreate(); settle(); assertNotNull(vm.visibleAction.draft); assertEquals(1, api.writes)
    }
    @Test fun excludedAndEmptyReadsCannotUnlockAndClearingFiltersStillNeedsAcknowledgement() = runBlocking {
        val api = Api().apply { failWrite = true }; val vm = model(api, this); vm.enter(); settle()
        apply(vm, BookingFilters(memberRef = ref(21))); settle(); create(vm); vm.reconcileOutcome(); settle()
        assertFalse(vm.canAcknowledge); vm.acknowledgeUncertain(); assertNotNull(vm.visiblePending)
        val count = api.reads.size
        apply(vm, BookingFilters(start = day.plusYears(1).atStartOfDay())); settle()
        assertEquals(count, api.reads.size); assertFalse(vm.canAcknowledge)
        apply(vm, BookingFilters()); settle(); assertTrue(vm.canAcknowledge); assertNotNull(vm.visiblePending)
        assertEquals(1, api.writes)
    }
    @Test fun uncertainEditAndCancelKeepReferenceAndNeverReplay() = runBlocking {
        for (mode in listOf(BookingSelection.EDIT, BookingSelection.CANCEL)) {
            val api = Api().apply { rows = listOf(row()); failWrite = true }
            val vm = model(api, this); vm.enter(); settle(); vm.selectMode(mode); vm.choose(ref(1)); settle()
            vm.submit(); settle(); assertEquals(ref(1), vm.visiblePending?.ref)
            assertEquals(if (mode == BookingSelection.EDIT) BookingOperation.EDIT else BookingOperation.CANCEL,
                vm.visiblePending?.operation)
            vm.reconcileOutcome(); settle(); assertTrue(vm.canAcknowledge)
            vm.acknowledgeUncertain(); assertEquals(1, api.writes); assertNull(vm.visiblePending)
            vm.leave()
        }
    }
    @Test fun pendingSurvivesLeaveReentryButNotIdentityChange() = runBlocking {
        var identity: BookingIdentity? = BookingIdentity("A", 1)
        val api = Api().apply { failWrite = true }; val vm = model(api, this, { identity })
        vm.enter(); settle(); create(vm); vm.leave(); assertNotNull(vm.visiblePending)
        vm.enter(); settle(); assertTrue(vm.canAcknowledge); assertNotNull(vm.visiblePending)
        identity = BookingIdentity("B", 2); assertNull(vm.visiblePending); vm.activate(2, 2); settle()
        assertNull(vm.visiblePending); assertEquals(BookingFilters(), vm.visibleFilters.applied)
        assertEquals(1, api.writes)
    }
    @Test fun reconciliationCoversOldAndNewPositionAndVehicle() {
        val original = row()
        val pending = BookingPending(BookingOperation.EDIT, original.ref, day.plusDays(1).atTime(12, 0),
            day.plusDays(1).atTime(14, 0), ref(11), original)
        val grid = bookingRange(YearMonth.from(day))
        assertTrue(pending.coveredBy(BookingQuery(grid)))
        assertFalse(pending.coveredBy(BookingQuery(grid, BookingFilters(vehicleRef = ref(11)))))
        assertFalse(pending.coveredBy(BookingQuery(grid, BookingFilters(start = day.plusDays(1).atStartOfDay()))))
        assertFalse(pending.coveredBy(BookingQuery(grid, BookingFilters(memberRef = ref(21)))))
    }
    @Test fun sheetStateDateChangesAndBackPriority() = runBlocking {
        val vm = model(Api(), this); vm.enter(); settle(); assertFalse(vm.sheetExpanded)
        vm.expandSheet(true); vm.selectDate(day.plusDays(1)); assertTrue(vm.sheetExpanded)
        assertTrue(vm.dismiss()); assertFalse(vm.sheetExpanded); assertFalse(vm.dismiss())
        vm.selectMode(BookingSelection.EDIT); assertTrue(vm.sheetExpanded)
        vm.selectDate(day); assertEquals(BookingSelection.EDIT, vm.visibleAction.selection)
        assertTrue(vm.dismiss()); assertEquals(BookingSelection.NONE, vm.visibleAction.selection)
        assertTrue(vm.sheetExpanded); assertTrue(vm.dismiss()); assertFalse(vm.dismiss())
        vm.openFilters(); assertTrue(vm.dismiss()); assertFalse(vm.visibleFilters.open)
        vm.expandSheet(true); vm.leave(); vm.enter(); settle(); assertFalse(vm.sheetExpanded)
    }
    @Test fun distantUncertainEditCanBeInspectedAcrossTwoBoundedReads() = runBlocking {
        val api = Api().apply { rows = listOf(row()); failWrite = true }
        val vm = model(api, this); vm.enter(); settle(); vm.selectMode(BookingSelection.EDIT); vm.choose(ref(1)); settle()
        vm.editDate(true, day.plusMonths(3)); vm.editDate(false, day.plusMonths(3)); vm.submit(); settle()
        vm.reconcileOutcome(); settle(); assertFalse(vm.canAcknowledge)
        assertTrue(checkNotNull(vm.visiblePending).proposedRead)
        vm.selectDate(day); settle(); assertTrue(vm.canAcknowledge)
        assertNotNull(vm.visiblePending); vm.acknowledgeUncertain(); assertNull(vm.visiblePending)
        assertEquals(1, api.writes)
    }
    @Test fun staleFilteredReadAfterMutationCannotRestoreOldRows() = runBlocking {
        val api = Api().apply { rows = listOf(row()) }; val vm = model(api, this); vm.enter(); settle()
        val filters = BookingFilters(vehicleRef = ref(10)); apply(vm, filters); settle()
        val old = CompletableDeferred<List<BookingReservation>>()
        api.response = { withContext(NonCancellable) { old.await() } }; vm.retry(); settle()
        vm.selectMode(BookingSelection.CANCEL); vm.choose(ref(1))
        api.response = { emptyList() }; vm.submit(); settle()
        old.complete(listOf(row())); settle(); assertTrue(vm.visibleData.rows.isEmpty())
        assertEquals(filters, vm.visibleFilters.applied); assertEquals(1, api.writes)
    }
    @Test fun activeSubmissionBlocksModalsBackAndLeavingKeepsUncertainty() = runBlocking {
        val delayed = CompletableDeferred<List<BookingReservation>>()
        val api = object : BookingGateway {
            override suspend fun reservations(owner: String, range: BookingRange) = emptyList<BookingReservation>()
            override suspend fun create(owner: String, change: BookingChange): BookingReservation {
                withContext(NonCancellable) { delayed.await() }; return row()
            }
        }
        val vm = BookingViewModel(api, { BookingIdentity("A", 1) }, this,
            vehicleLoad = { listOf(vehicle()) }, now = { day.atTime(10, 0) }, today = { day })
        vm.enter(); settle(); vm.openCreate(); settle()
        vm.editTime(true, LocalTime.NOON); vm.editTime(false, LocalTime.of(14, 0)); vm.submit(); settle()
        assertTrue(vm.visibleAction.submitting); assertTrue(vm.dismiss()); assertNotNull(vm.visibleAction.draft)
        vm.openFilters(); assertFalse(vm.visibleFilters.open)
        vm.leave(); assertNotNull(vm.visiblePending); vm.enter(); settle()
        delayed.complete(emptyList()); settle(); assertNotNull(vm.visiblePending)
        assertTrue(vm.canAcknowledge); assertTrue(vm.visibleAction.reconciling)
    }
}

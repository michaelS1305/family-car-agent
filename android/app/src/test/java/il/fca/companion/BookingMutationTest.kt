package il.fca.companion

import android.app.Application
import il.fca.companion.net.*
import il.fca.companion.ui.*
import kotlinx.coroutines.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.time.*

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class BookingMutationTest {
    private val date = LocalDate.of(2026, 10, 15)
    private val clock = date.atTime(10, 0)
    private fun ref(n: Int) = "00000000-0000-0000-0000-%012d".format(n)
    private fun row(n: Int = 1) = BookingReservation(ref(n), "שם", ref(99), date.atTime(12, 0, 23),
        date.atTime(14, 0, 45), true, null, null, null)
    private fun vehicle(n: Int = 1, retired: Boolean = false) = ManagedVehicle(ref(n), "רכב", Instant.EPOCH,
        if (retired) Instant.EPOCH else null, VehicleCategory.SEDAN, null, null, null, null)
    private fun json(row: BookingReservation = row()) = JSONObject().put("reservation_ref", row.ref)
        .put("owner_name", row.ownerName).put("member_ref", row.memberRef).put("is_mine", row.isMine)
        .put("start_time", row.start.toString()).put("end_time", row.end.toString())
        .put("vehicle_ref", row.vehicleRef ?: JSONObject.NULL).put("vehicle_display_name", row.vehicleName ?: JSONObject.NULL)
        .put("vehicle_category", row.category?.wire ?: JSONObject.NULL)
    private class Fake : BookingGateway {
        var rows = emptyList<BookingReservation>()
        val reads = mutableListOf<BookingRange>()
        val writes = mutableListOf<Triple<String, String?, BookingChange?>>()
        var read: suspend (BookingRange) -> List<BookingReservation> = { rows }
        var write: suspend () -> Unit = {}
        override suspend fun reservations(owner: String, range: BookingRange): List<BookingReservation> {
            reads += range; return read(range)
        }
        override suspend fun create(owner: String, change: BookingChange): BookingReservation {
            writes += Triple(owner, null, change); write()
            return BookingReservation("00000000-0000-0000-0000-000000000010", "שם", "00000000-0000-0000-0000-000000000099",
                change.start, change.end, true, change.vehicleRef, null, null).also { rows = rows + it }
        }
        override suspend fun update(owner: String, ref: String, change: BookingChange): BookingReservation {
            writes += Triple(owner, ref, change); write()
            return rows.single { it.ref == ref }.copy(start = change.start, end = change.end,
                vehicleRef = if (change.includeVehicle) change.vehicleRef else rows.single { it.ref == ref }.vehicleRef)
                .also { saved -> rows = rows.map { if (it.ref == ref) saved else it } }
        }
        override suspend fun cancel(owner: String, ref: String) {
            writes += Triple(owner, ref, null); write(); rows = rows.filterNot { it.ref == ref }
        }
    }
    private fun model(api: Fake, scope: CoroutineScope, identity: () -> BookingIdentity? = { BookingIdentity("A", 1) },
        vehicles: suspend (String) -> List<ManagedVehicle> = { emptyList() }) =
        BookingViewModel(api, identity, scope, vehicles, { clock }) { date }
    private suspend fun settle() { repeat(10) { yield() } }
    private suspend fun createForm(vm: BookingViewModel) {
        vm.enter(); settle(); vm.openCreate(); settle()
        vm.editTime(true, LocalTime.of(12, 0)); vm.editTime(false, LocalTime.of(14, 0))
    }

    @Test fun endpointsBodiesPublicRefsAndSuccessParsing() = runBlocking {
        val calls = mutableListOf<Triple<String, String, JSONObject>>()
        val api = BookingApi { owner, path, method, body ->
            assertEquals("A", owner); calls += Triple(path, method, body)
            if (path.endsWith("cancel")) "{\"cancelled\":true}" else json().toString()
        }
        val change = BookingChange(row().start, row().end)
        assertEquals(row(), api.create("A", change))
        api.update("A", ref(1), change); api.cancel("A", ref(1))
        assertEquals(listOf("POST", "PATCH", "POST"), calls.map { it.second })
        assertEquals(listOf("/api/reservations", "/api/reservations", "/api/reservations/cancel"), calls.map { it.first })
        assertEquals(setOf("start_time", "end_time"), calls[0].third.keys().asSequence().toSet())
        assertEquals(ref(1), calls[1].third.getString("reservation_ref"))
        assertEquals(setOf("reservation_ref"), calls[2].third.keys().asSequence().toSet())
        assertFalse(change.json().has("vehicle_ref"))
        assertTrue(change.copy(includeVehicle = true).json().isNull("vehicle_ref"))
        assertEquals(ref(2), change.copy(vehicleRef = ref(2), includeVehicle = true).json().getString("vehicle_ref"))
    }
    @Test fun malformedMutationSuccessIsNotSuccess() = runBlocking {
        for (body in listOf("{}", "[]", "bad", json().put("reservation_ref", JSONObject.NULL).toString())) {
            val api = BookingApi { _, _, _, _ -> body }
            assertTrue(runCatching { api.create("A", BookingChange(row().start, row().end)) }.isFailure)
        }
        assertTrue(runCatching { BookingApi { _, _, _, _ -> "{\"cancelled\":false}" }.cancel("A", ref(1)) }.isFailure)
        assertTrue(runCatching { BookingApi { _, _, _, _ -> json(row(2)).toString() }
            .update("A", ref(1), BookingChange(row().start, row().end)) }.isFailure)
    }
    @Test fun allowlistedErrorsDoNotRetainServerTextAndDeliveryUnchanged() {
        val codes = mapOf("RESERVATION_CONFLICT" to 409, "VEHICLE_REQUIRED" to 409, "RESERVATION_AMBIGUOUS" to 409,
            "VEHICLE_NOT_FOUND_OR_UNAVAILABLE" to 404, "RESERVATION_NOT_FOUND_OR_UNAVAILABLE" to 404,
            "INVALID_RESERVATION_TIME" to 422, "RESERVATION_TIME_IN_PAST" to 422)
        codes.forEach { (code, status) ->
            val body = "{\"detail\":{\"code\":\"$code\",\"message\":\"private\",\"vehicles\":[\"untrusted\"]}}"
            assertEquals(code, BookingFailure.parse(status, body).code)
            assertEquals("HTTP $status", BookingFailure.parse(status, body).message)
            assertNull(BookingFailure.parse(500, body).code)
        }
        assertNull(BookingFailure.parse(409, "bad").code)
        assertNull(BookingFailure.parse(409, "{\"detail\":{\"code\":\"UNKNOWN\"}}").code)
        val connection = object : HttpURLConnection(URL("https://example.invalid")) {
            override fun connect() = Unit
            override fun disconnect() = Unit
            override fun usingProxy() = false
            override fun getErrorStream() = "{\"detail\":{\"code\":\"RESERVATION_CONFLICT\"}}".byteInputStream()
        }
        assertNull(Http.failure(connection, 409).diagnosticCode)
        assertFalse(BookingFailure.supports("/api/device-events", "POST"))
        assertFalse(BookingFailure.supports("/api/reservations", "GET"))
    }
    @Test fun one401RefreshAndNoTransportOrBusinessRetries() {
        for (failure in listOf(BookingFailure(401), HttpFailure(401))) {
            val calls = mutableListOf<Boolean>()
            assertEquals("ok", bookingAuthenticated { force -> calls += force; if (!force) throw failure; "ok" })
            assertEquals(listOf(false, true), calls)
        }
        for (failure in listOf(BookingFailure(409), IOException(), BookingFailure(500))) {
            var count = 0
            assertTrue(runCatching { bookingAuthenticated { count++; throw failure } }.isFailure)
            assertEquals(1, count)
        }
        var count = 0
        assertTrue(runCatching { bookingAuthenticated { count++; throw BookingFailure(401) } }.isFailure)
        assertEquals(2, count)
    }
    @Test fun datesTimesAndZeroOneMultipleVehiclePolicy() = runBlocking {
        for (vehicles in listOf(emptyList(), listOf(vehicle()), listOf(vehicle(), vehicle(2)))) {
            val api = Fake(); val vm = model(api, this, vehicles = { vehicles })
            vm.enter(); settle(); vm.selectDate(date.minusDays(1)); settle(); vm.openCreate(); settle()
            assertEquals(date, vm.visibleAction.draft?.startDate)
            assertNull(vm.visibleAction.draft?.startTime)
            vm.submit(); settle(); assertTrue(api.writes.isEmpty())
            vm.editTime(true, LocalTime.NOON); vm.editTime(false, LocalTime.of(14, 0))
            if (vehicles.size > 1) {
                assertNull(vm.visibleAction.draft?.vehicleRef); vm.submit(); settle(); assertTrue(api.writes.isEmpty())
                vm.chooseVehicle(ref(2))
            }
            vm.submit(); settle(); assertEquals(1, api.writes.size)
            assertEquals(vehicles.lastOrNull()?.ref, api.writes.single().third?.vehicleRef)
            vm.leave()
        }
    }
    @Test fun futureDefaultsInvalidIntervalAndVehicleFailureRetry() = runBlocking {
        val api = Fake(); var fails = true
        val vm = model(api, this, vehicles = { if (fails) throw IOException() else listOf(vehicle()) })
        vm.enter(); settle(); vm.selectDate(date.plusDays(5)); settle(); vm.openCreate(); settle()
        assertEquals(date.plusDays(5), vm.visibleAction.draft?.endDate)
        assertTrue(vm.visibleAction.vehicleError)
        vm.editTime(true, LocalTime.NOON); vm.editTime(false, LocalTime.NOON); vm.submit(); settle()
        assertTrue(api.writes.isEmpty())
        vm.editTime(false, LocalTime.of(14, 0)); vm.submit(); settle(); assertTrue(api.writes.isEmpty())
        fails = false; vm.loadVehicles(); settle(); vm.submit(); settle(); assertEquals(1, api.writes.size)
        assertEquals(date.plusDays(5), vm.selectedDate)
    }
    @Test fun duplicateSubmitAndBackBlockedUntilConfirmedSuccess() = runBlocking {
        val gate = CompletableDeferred<Unit>(); val api = Fake().apply { write = { gate.await() } }
        val vm = model(api, this); createForm(vm)
        vm.submit(); vm.submit(); assertTrue(vm.visibleAction.submitting); assertTrue(vm.dismiss()); settle()
        assertEquals(1, api.writes.size); assertNotNull(vm.visibleAction.draft)
        gate.complete(Unit); settle()
        assertNull(vm.visibleAction.draft); assertFalse(vm.visibleAction.submitting)
        assertEquals(1, vm.visibleData.rows.size); assertEquals(2, api.reads.size)
    }
    @Test fun ownershipEndedAndConfirmationBeforeCancel() = runBlocking {
        val api = Fake().apply { rows = listOf(row(), row(2).copy(isMine = false), row(3).copy(end = clock)) }
        val vm = model(api, this); vm.enter(); settle(); vm.selectMode(BookingSelection.CANCEL)
        vm.choose(ref(2)); assertNull(vm.visibleAction.confirmation)
        vm.choose(ref(3)); assertNull(vm.visibleAction.confirmation)
        vm.choose(ref(1)); assertNotNull(vm.visibleAction.confirmation); assertTrue(api.writes.isEmpty())
        vm.submit(); vm.submit(); settle()
        assertEquals(1, api.writes.size); assertFalse(vm.visibleData.rows.any { it.ref == ref(1) })
        assertEquals(BookingSelection.NONE, vm.visibleAction.selection)
    }
    @Test fun ongoingEditPreservesSecondsAndGeneralLinkAndCanCancel() = runBlocking {
        val original = row().copy(start = date.atTime(8, 0, 23))
        val api = Fake().apply { rows = listOf(original) }; val vm = model(api, this)
        vm.enter(); settle(); vm.selectMode(BookingSelection.EDIT); vm.choose(ref(1)); settle()
        assertEquals(original.start, vm.visibleAction.draft?.start)
        vm.editTime(false, LocalTime.of(15, 0, 22)); vm.submit(); settle()
        assertEquals(original.start, api.writes.single().third?.start)
        assertEquals(0, api.writes.single().third?.end?.second)
        assertFalse(checkNotNull(api.writes.single().third).includeVehicle)
        vm.selectMode(BookingSelection.CANCEL); vm.choose(ref(1)); vm.submit(); settle()
        assertTrue(vm.visibleData.rows.isEmpty())
    }
    @Test fun ongoingPastStartCannotBeChangedByMinutePicker() = runBlocking {
        val api = Fake().apply { rows = listOf(row().copy(start = date.atTime(8, 0, 23))) }; val vm = model(api, this)
        vm.enter(); settle(); vm.selectMode(BookingSelection.EDIT); vm.choose(ref(1)); settle()
        vm.editTime(true, LocalTime.of(8, 0)); vm.editDate(true, date.plusDays(1))
        assertEquals(date.atTime(8, 0, 23), vm.visibleAction.draft?.start)
        vm.submit(); settle(); assertEquals(date.atTime(8, 0, 23), api.writes.single().third?.start)
    }
    @Test fun retiredLinkPreservedNoGeneralConversionAndActiveReassignment() = runBlocking {
        val api = Fake().apply { rows = listOf(row().copy(vehicleRef = ref(1), vehicleName = "ישן")) }
        val vm = model(api, this, vehicles = { listOf(vehicle(1, true), vehicle(2)) })
        vm.enter(); settle(); vm.selectMode(BookingSelection.EDIT); vm.choose(ref(1)); settle()
        vm.chooseVehicle(null); assertEquals(ref(1), vm.visibleAction.draft?.vehicleRef)
        vm.submit(); settle(); assertFalse(checkNotNull(api.writes.last().third).includeVehicle)
        vm.selectMode(BookingSelection.EDIT); vm.choose(ref(1)); settle(); vm.chooseVehicle(ref(2)); vm.submit(); settle()
        assertEquals(ref(2), api.writes.last().third?.vehicleRef); assertTrue(checkNotNull(api.writes.last().third).includeVehicle)
    }
    @Test fun confirmedRejectionKeepsDraftAndDistinctMessage() = runBlocking {
        val api = Fake().apply { write = { throw BookingFailure(409, "RESERVATION_CONFLICT") } }
        val vm = model(api, this); createForm(vm); val draft = vm.visibleAction.draft
        vm.submit(); settle(); assertEquals(draft, vm.visibleAction.draft)
        assertEquals(bookingRejection("RESERVATION_CONFLICT"), vm.visibleAction.error)
        assertFalse(vm.visibleAction.uncertain)
    }
    @Test fun uncertainOutcomeRequiresReadBeforeAnotherWrite() = runBlocking {
        val api = Fake().apply { write = { throw IOException() } }; val vm = model(api, this)
        createForm(vm); vm.submit(); settle(); assertTrue(vm.visibleAction.uncertain)
        vm.submit(); settle(); assertEquals(1, api.writes.size)
        val pending = CompletableDeferred<List<BookingReservation>>()
        api.read = { pending.await() }; vm.reconcileOutcome(); settle(); vm.openCreate()
        assertNull(vm.visibleAction.draft); assertTrue(vm.visibleAction.reconciling)
        pending.complete(emptyList()); settle(); vm.openCreate(); settle(); assertNull(vm.visibleAction.draft)
        assertTrue(vm.canAcknowledge)
        vm.acknowledgeUncertain(); vm.openCreate(); settle(); assertNotNull(vm.visibleAction.draft)
        assertEquals(1, api.writes.size)
    }
    @Test fun identityChangeDuringMutationRejectsLateResult() = runBlocking {
        var identity: BookingIdentity? = BookingIdentity("A", 1)
        val pending = CompletableDeferred<Unit>()
        val api = Fake().apply { write = { withContext(NonCancellable) { pending.await() } } }
        val vm = model(api, this, { identity }); createForm(vm); vm.submit(); settle()
        identity = BookingIdentity("B", 2); assertNull(vm.visibleAction.draft)
        vm.activate(2, 2); settle(); pending.complete(Unit); settle()
        assertTrue(vm.visibleData.rows.isEmpty()); assertNull(vm.visibleAction.notice)
        assertEquals("A", api.writes.single().first)
    }
    @Test fun familyChangeDuringVehicleLoadRejectsOldCatalog() = runBlocking {
        var identity = BookingIdentity("A", 1); val pending = CompletableDeferred<List<ManagedVehicle>>()
        val vm = model(Fake(), this, { identity }, { withContext(NonCancellable) { pending.await() } })
        vm.enter(); settle(); vm.openCreate(); settle(); identity = BookingIdentity("A", 2); vm.activate(1, 2)
        pending.complete(listOf(vehicle())); settle()
        assertTrue(vm.visibleAction.vehicles.isEmpty()); assertNull(vm.visibleAction.draft)
    }
    @Test fun oldGetCannotOverwritePostMutationRefresh() = runBlocking {
        val api = Fake(); val vm = model(api, this); createForm(vm)
        val old = CompletableDeferred<List<BookingReservation>>()
        api.read = { withContext(NonCancellable) { old.await() } }; vm.retry(); settle()
        api.read = { api.rows }; vm.submit(); settle(); assertEquals(1, vm.visibleData.rows.size)
        old.complete(emptyList()); settle(); assertEquals(1, vm.visibleData.rows.size)
    }
    @Test fun editAcrossMonthsRefreshFailureIsNotMutationFailure() = runBlocking {
        val api = Fake().apply { rows = listOf(row()) }; val vm = model(api, this)
        vm.enter(); settle(); vm.selectMode(BookingSelection.EDIT); vm.choose(ref(1)); settle()
        vm.editDate(true, date.plusMonths(1)); vm.editDate(false, date.plusMonths(1))
        api.read = { throw IOException() }; vm.submit(); settle()
        assertNull(vm.visibleAction.draft); assertEquals("ההזמנה נשמרה.", vm.visibleAction.notice)
        assertEquals(date.plusMonths(1), vm.selectedDate); assertTrue(vm.visibleData.error)
        api.read = { api.rows }; vm.retry(); settle(); assertEquals(1, api.writes.size)
        assertEquals(1, vm.visibleData.rows.size)
    }
    @Test fun outOfPagerRangeDoesNotClaimVisibleAndBackPriority() = runBlocking {
        val api = Fake(); val vm = model(api, this); createForm(vm)
        vm.editDate(true, date.plusYears(20)); vm.editDate(false, date.plusYears(20)); vm.submit(); settle()
        assertEquals(date, vm.selectedDate); assertTrue(checkNotNull(vm.visibleAction.notice).contains("מחוץ לטווח"))
        vm.selectMode(BookingSelection.EDIT); assertTrue(vm.dismiss()); assertTrue(vm.dismiss()); assertFalse(vm.dismiss())
        vm.openCreate(); settle(); assertTrue(vm.dismiss()); assertFalse(vm.dismiss())
    }
    @Test fun monthNavigationDoesNotCancelMutationAndSavedMonthWins() = runBlocking {
        val pending = CompletableDeferred<Unit>(); val api = Fake().apply { write = { pending.await() } }
        val vm = model(api, this); createForm(vm); vm.submit(); settle()
        vm.nextMonth(); settle(); assertTrue(vm.visibleAction.submitting)
        pending.complete(Unit); settle()
        assertEquals(YearMonth.from(date), vm.visibleMonth)
        assertEquals(bookingRange(vm.visibleMonth), vm.visibleData.loaded)
        assertEquals(1, api.writes.size)
    }
    @Test fun generalEditCanChangeToActiveAndDateOnlyPreservesSeconds() = runBlocking {
        val api = Fake().apply { rows = listOf(row()) }; val vm = model(api, this, vehicles = { listOf(vehicle(2)) })
        vm.enter(); settle(); vm.selectMode(BookingSelection.EDIT); vm.choose(ref(1)); settle()
        assertNull(vm.visibleAction.draft?.vehicleRef)
        vm.editDate(true, date.plusDays(1)); vm.editDate(false, date.plusDays(1))
        assertEquals(23, vm.visibleAction.draft?.startTime?.second)
        assertEquals(45, vm.visibleAction.draft?.endTime?.second)
        vm.chooseVehicle(ref(2)); vm.submit(); settle()
        assertEquals(ref(2), api.writes.single().third?.vehicleRef)
        assertTrue(checkNotNull(api.writes.single().third).includeVehicle)
    }
    @Test fun cancelledAndUnknownCancellationDoNotBlindlyRetry() = runBlocking {
        for (failure in listOf(BookingFailure(404, "RESERVATION_NOT_FOUND_OR_UNAVAILABLE"), IOException())) {
            val api = Fake().apply { rows = listOf(row()); write = { throw failure } }
            val vm = model(api, this); vm.enter(); settle(); vm.selectMode(BookingSelection.CANCEL); vm.choose(ref(1))
            vm.submit(); vm.submit(); settle(); assertEquals(1, api.writes.size)
            assertNotNull(vm.visibleAction.confirmation)
            assertEquals(failure !is BookingFailure, vm.visibleAction.uncertain)
            assertNotNull(vm.visibleAction.error); vm.leave()
        }
    }
    @Test fun vehicleRefreshDeduplicatesAndRetainsChoicesButBlocksFailedRefreshSubmit() = runBlocking {
        var calls = 0; var fail = false; val pending = CompletableDeferred<List<ManagedVehicle>>()
        val vm = model(Fake(), this, vehicles = { calls++; if (calls == 1) pending.await()
            else if (fail) throw IOException() else listOf(vehicle()) })
        vm.enter(); settle(); vm.openCreate(); vm.loadVehicles(); vm.loadVehicles(); settle()
        assertEquals(1, calls); pending.complete(listOf(vehicle())); settle()
        fail = true; vm.loadVehicles(); settle()
        assertEquals(listOf(vehicle()), vm.visibleAction.vehicles)
        assertTrue(vm.visibleAction.vehicleError)
    }
    @Test fun reconciliationUsesDraftDateAndReadFailureKeepsWritesBlocked() = runBlocking {
        val api = Fake().apply { write = { throw IOException() } }; val vm = model(api, this)
        createForm(vm); vm.editDate(true, date.plusMonths(1)); vm.editDate(false, date.plusMonths(1))
        vm.submit(); settle(); api.read = { throw IOException() }; vm.reconcileOutcome(); settle()
        assertEquals(date.plusMonths(1), vm.selectedDate); assertTrue(vm.visibleAction.reconciling)
        vm.openCreate(); assertNull(vm.visibleAction.draft); assertEquals(1, api.writes.size)
    }
    @Test fun familyChangeDuringWriteAndLogoutHideEveryActionImmediately() = runBlocking {
        var identity: BookingIdentity? = BookingIdentity("A", 1)
        val gate = CompletableDeferred<Unit>(); val api = Fake().apply { write = { withContext(NonCancellable) { gate.await() } } }
        val vm = model(api, this, { identity }); createForm(vm); vm.submit(); settle()
        identity = BookingIdentity("A", 2); assertEquals(BookingAction(), vm.visibleAction)
        vm.activate(1, 2); settle(); gate.complete(Unit); settle()
        assertTrue(vm.visibleData.rows.isEmpty()); assertNull(vm.visibleAction.notice)
        vm.openCreate(); settle(); identity = null
        assertEquals(BookingAction(), vm.visibleAction); assertTrue(vm.visibleData.rows.isEmpty())
        vm.activate(2, null); assertNull(vm.visibleAction.draft)
    }
    @Test fun rejectedCreateRestartsInitialReadCancelledBySubmission() = runBlocking {
        val pending = CompletableDeferred<List<BookingReservation>>()
        val api = Fake().apply { read = { pending.await() }; write = { throw BookingFailure(409, "RESERVATION_CONFLICT") } }
        val vm = model(api, this); createForm(vm)
        api.read = { emptyList() }; vm.submit(); settle(); vm.dismiss()
        assertEquals(bookingRange(vm.visibleMonth), vm.visibleData.loaded)
        assertFalse(vm.visibleData.loading)
    }
    @Test fun eligibilityIsRecheckedWhenClockAdvancesBeforeSubmit() = runBlocking {
        var time = clock
        val api = Fake().apply { rows = listOf(row()) }
        val vm = BookingViewModel(api, { BookingIdentity("A", 1) }, this,
            vehicleLoad = { emptyList() }, now = { time }) { date }
        vm.enter(); settle(); vm.selectMode(BookingSelection.CANCEL); vm.choose(ref(1))
        time = row().end; vm.submit(); settle()
        assertTrue(api.writes.isEmpty()); assertNotNull(vm.visibleAction.error)
    }
}

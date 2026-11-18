package il.fca.companion

import android.app.Application
import il.fca.companion.net.*
import il.fca.companion.ui.*
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.YearMonth
import java.net.URLDecoder

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class BookingDataTest {
    private val day = LocalDate.of(2026, 10, 15)
    private fun ref(n: Int) = "00000000-0000-0000-0000-%012d".format(n)
    private fun row(n: Int = 1, start: String = "2026-10-15T10:00:00", end: String = "2026-10-15T12:00:00") =
        BookingReservation(ref(n), "משתמש", ref(99), LocalDateTime.parse(start), LocalDateTime.parse(end), true, null, null, null)
    private fun json() = JSONObject().put("reservation_ref", ref(1)).put("member_ref", ref(99))
        .put("owner_name", "משתמש").put("start_time", "2026-10-15T10:00:00").put("end_time", "2026-10-15T12:00:00")
        .put("is_mine", true).put("vehicle_ref", JSONObject.NULL).put("vehicle_display_name", JSONObject.NULL)
        .put("vehicle_category", JSONObject.NULL)
    private fun parse(obj: JSONObject) = BookingApi.parse(JSONArray().put(obj).toString()).single()
    private class Gateway : BookingGateway {
        val calls = mutableListOf<Pair<String, BookingRange>>()
        var action: suspend (BookingRange) -> List<BookingReservation> = { emptyList() }
        override suspend fun reservations(owner: String, range: BookingRange): List<BookingReservation> {
            calls += owner to range
            return action(range)
        }
    }
    private fun vm(api: Gateway, scope: CoroutineScope, identity: () -> BookingIdentity? = { BookingIdentity("A", 1) }) =
        BookingViewModel(api, identity, scope) { day }
    private suspend fun settle() { repeat(5) { yield() } }

    @Test fun bookingProjectionPreservesAssociatedVehicleCategories() {
        val rows = VehicleCategory.entries.mapIndexed { i, category ->
            parse(json().put("reservation_ref", ref(i + 1)).put("vehicle_ref", ref(i + 10))
                .put("vehicle_display_name", "same name").put("vehicle_category", category.wire))
        }
        val projected = bookingRows(rows.reversed(), day)
        rows.forEach { expected ->
            val actual = projected.single { it.ref == expected.ref }
            assertEquals(expected.vehicleRef, actual.vehicleRef)
            assertEquals(vehicleIllustration(expected.category), vehicleIllustration(actual.category))
        }
        assertEquals(R.drawable.single_car_icon, vehicleIllustration(parse(json()).category))
    }

    @Test fun queryUsesGridAndOnlyBoundedPublicParameters() {
        val path = URLDecoder.decode(BookingApi.path(BookingRange(day, day.plusDays(35))), "UTF-8")
        assertEquals("/api/reservations?range_start=2026-10-15T00:00:00&range_end=2026-11-19T00:00:00&scope=all", path)
    }
    @Test fun localAndOffsetTimesNormalizeWithoutUtcProjection() {
        assertEquals(row().start, parse(json()).start)
        assertEquals(LocalDateTime.of(2026, 10, 15, 10, 0), BookingApi.time("2026-10-15T07:00:00Z"))
        assertEquals(LocalDateTime.of(2026, 11, 5, 10, 0), BookingApi.time("2026-11-05T08:00:00+00:00"))
        assertEquals(123456000, BookingApi.time("2026-10-15T10:00:00.123456").nano)
        for (value in listOf("bad", "2026-10-15", "2026-02-30T10:00:00", "2026-10-15T10:00:00+99:00")) {
            assertTrue(runCatching { BookingApi.time(value) }.isFailure)
        }
    }
    @Test fun nullableAndCanonicalVehicleMetadata() {
        assertNull(parse(json()).vehicleRef)
        for (category in VehicleCategory.entries) {
            val result = parse(json().put("vehicle_ref", ref(3)).put("vehicle_display_name", "רכב").put("vehicle_category", category.wire))
            assertEquals(category, result.category)
        }
        assertNull(parse(json().put("vehicle_ref", ref(3)).put("vehicle_display_name", "רכב")).category)
    }
    @Test fun missingNullAndMalformedIdentityFailClosed() {
        for (key in listOf("reservation_ref", "member_ref")) {
            for (value in listOf(JSONObject.NULL, "bad", 123)) assertTrue(runCatching { parse(json().put(key, value)) }.isFailure)
            assertTrue(runCatching { parse(json().also { it.remove(key) }) }.isFailure)
        }
    }
    @Test fun invalidFieldsIntervalsCategoriesAndDuplicatesFailClosed() {
        for ((key, value) in listOf("is_mine" to "true", "owner_name" to 3, "vehicle_category" to "unknown",
            "end_time" to "2026-10-15T10:00:00", "vehicle_ref" to "bad")) {
            assertTrue(runCatching { parse(json().put(key, value)) }.isFailure)
        }
        for (key in listOf("owner_name", "is_mine", "vehicle_category", "vehicle_ref", "vehicle_display_name", "start_time", "end_time"))
            assertTrue(runCatching { parse(json().also { it.remove(key) }) }.isFailure)
        assertTrue(runCatching { BookingApi.parse(JSONArray().put(json()).put(json()).toString()) }.isFailure)
    }
    @Test fun rangesHave28_35_42DaysAndAdjacentCoverage() {
        for ((month, count) in listOf(YearMonth.of(2026, 2) to 28L, YearMonth.of(2026, 4) to 35L, YearMonth.of(2026, 5) to 42L)) {
            val range = bookingRange(month)
            val dates = bookingMonthDays(month)
            assertEquals(dates.first(), range.start)
            assertEquals(dates.last().plusDays(1), range.endExclusive)
            assertEquals(count, java.time.temporal.ChronoUnit.DAYS.between(range.start, range.endExclusive))
            assertFalse(range.endExclusive in range)
        }
    }
    @Test fun halfOpenOverlapMidnightAndOneDot() {
        val overnight = row(start = "2026-10-15T22:00:00", end = "2026-10-16T08:00:00")
        assertTrue(overnight.overlaps(day)); assertTrue(overnight.overlaps(day.plusDays(1)))
        val midnight = overnight.copy(end = day.plusDays(1).atStartOfDay())
        assertFalse(midnight.overlaps(day.plusDays(1)))
        assertTrue(midnight.copy(start = day.atStartOfDay()).overlaps(day))
        assertEquals(setOf(day), bookingDots(listOf(midnight, row(2)), BookingRange(day, day.plusDays(2))))
        assertTrue(bookingDots(listOf(row()), BookingRange(day.plusDays(1), day.plusDays(2))).isEmpty())
    }
    @Test fun rowsSortDescendingThenByPublicReferenceAndShowActualEndpoints() {
        val early = row(3)
        val late = row(2, "2026-10-15T11:00:00", "2026-10-15T13:00:00")
        assertEquals(listOf(ref(1), ref(2), ref(3)), bookingRows(listOf(early, late, late.copy(ref = ref(1))), day).map { it.ref })
        assertEquals("10:00 – 12:00", bookingTimeLabel(early))
        assertEquals("15.10 22:00 – 16.10 08:00", bookingTimeLabel(row(start = "2026-10-15T22:00:00", end = "2026-10-16T08:00:00")))
    }
    @Test fun dstUsesLocalDatesNotElapsed24Hours() {
        val range = BookingRange(LocalDate.of(2026, 10, 1), LocalDate.of(2026, 11, 12))
        val crossing = row(start = "2026-10-24T22:00:00", end = "2026-10-26T00:00:00")
        assertEquals(setOf(LocalDate.of(2026, 10, 24), LocalDate.of(2026, 10, 25)), bookingDots(listOf(crossing), range))
    }
    @Test fun initialLoadDedupSelectionAndMonthChange() = runBlocking {
        val api = Gateway().apply { action = { listOf(row()) } }; val model = vm(api, this)
        model.enter(); model.enter(); model.activate(1, 1); settle()
        assertEquals(1, api.calls.size); assertEquals(listOf(row()), model.visibleData.rows)
        model.selectDate(day.plusDays(1)); settle(); assertEquals(1, api.calls.size)
        model.nextMonth(); assertTrue(model.visibleData.rows.isEmpty()); settle()
        assertEquals(2, api.calls.size); assertEquals(bookingRange(model.visibleMonth), model.visibleData.loaded)
        model.leave()
    }
    @Test fun entryRefreshRetainsDataAndFailureDoesNotFakeEmpty() = runBlocking {
        val api = Gateway().apply { action = { listOf(row()) } }; val model = vm(api, this)
        model.enter(); settle(); model.leave()
        assertEquals(listOf(row()), model.visibleData.rows)
        val pending = CompletableDeferred<List<BookingReservation>>()
        api.action = { pending.await() }
        model.enter(); settle()
        assertTrue(model.visibleData.refreshing); assertEquals(listOf(row()), model.visibleData.rows)
        pending.completeExceptionally(IllegalStateException("test")); settle()
        assertTrue(model.visibleData.error); assertEquals(listOf(row()), model.visibleData.rows)
        assertFalse(model.visibleData.refreshing)
        api.action = { emptyList() }; model.retry(); settle()
        assertFalse(model.visibleData.error); assertTrue(model.visibleData.rows.isEmpty())
        model.leave()
    }
    @Test fun initialFailureAndRetry() = runBlocking {
        val api = Gateway().apply { action = { error("test") } }; val model = vm(api, this)
        model.enter(); settle()
        assertTrue(model.visibleData.error); assertNull(model.visibleData.loaded); assertFalse(model.visibleData.loading)
        api.action = { listOf(row()) }; model.retry(); settle()
        assertEquals(listOf(row()), model.visibleData.rows); assertFalse(model.visibleData.error); model.leave()
    }
    @Test fun outOfOrderResponsesCannotReplaceFinalMonth() = runBlocking {
        val old = CompletableDeferred<List<BookingReservation>>()
        val api = Gateway().apply { action = { withContext(NonCancellable) { old.await() } } }
        val model = vm(api, this); model.enter(); settle()
        api.action = { listOf(row(2)) }; model.nextMonth(); model.nextMonth(); settle()
        old.complete(listOf(row(1))); settle()
        assertEquals(listOf(row(2)), model.visibleData.rows)
        assertEquals(bookingRange(model.visibleMonth), model.visibleData.loaded); model.leave()
    }
    @Test fun accountAndFamilyChangesRejectInflightDataAndMaskImmediately() = runBlocking {
        for (next in listOf(BookingIdentity("B", 1), BookingIdentity("A", 2))) {
            var who: BookingIdentity? = BookingIdentity("A", 1)
            val pending = CompletableDeferred<List<BookingReservation>>()
            val api = Gateway().apply { action = { withContext(NonCancellable) { pending.await() } } }
            val model = vm(api, this) { who }; model.enter(); settle()
            who = next
            assertTrue(model.visibleData.rows.isEmpty())
            api.action = { listOf(row(2)) }; model.activate(2, next.family); settle()
            pending.complete(listOf(row(1))); settle()
            assertEquals(listOf(row(2)), model.visibleData.rows)
            assertEquals(next.owner, api.calls.last().first)
            who = null; assertTrue(model.visibleData.rows.isEmpty()); model.activate(3, null)
            assertNull(model.visibleData.loaded); model.leave()
        }
    }
    @Test fun initialGuardIsObservableAndLeaveIgnoresLateResult() = runBlocking {
        val pending = CompletableDeferred<List<BookingReservation>>()
        val api = Gateway().apply { action = { withContext(NonCancellable) { pending.await() } } }
        val model = vm(api, this)
        var invalidations = 0
        val observer = androidx.compose.runtime.snapshots.SnapshotStateObserver { it() }
        observer.start()
        try {
            observer.observeReads(Any(), { _: Any -> invalidations++ }) { model.visibleData }
            model.enter(); settle(); androidx.compose.runtime.snapshots.Snapshot.sendApplyNotifications()
            assertTrue(invalidations > 0)
            model.leave(); pending.complete(listOf(row())); settle()
            assertNull(model.visibleData.loaded)
        } finally { observer.stop(); observer.clear(); model.leave() }
    }
    @Test fun pendingRetryIsDeduplicatedAndLoadedIdentityIsHiddenBeforeActivation() = runBlocking {
        var who: BookingIdentity? = BookingIdentity("A", 1)
        val pending = CompletableDeferred<List<BookingReservation>>()
        val api = Gateway().apply { action = { pending.await() } }
        val model = vm(api, this) { who }
        model.enter(); model.retry(); model.enter(); settle()
        assertEquals(1, api.calls.size)
        pending.complete(listOf(row())); settle()
        assertEquals(listOf(row()), model.visibleData.rows)
        who = BookingIdentity("A", 2)
        assertTrue(model.visibleData.rows.isEmpty()); assertNull(model.visibleData.loaded)
        api.action = { emptyList() }; model.activate(1, 2); settle()
        assertTrue(model.visibleData.rows.isEmpty()); assertNotNull(model.visibleData.loaded)
        model.leave()
    }
}

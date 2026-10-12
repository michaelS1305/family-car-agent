package il.fca.companion

import android.app.Application
import il.fca.companion.net.*
import il.fca.companion.ui.*
import java.net.URLDecoder
import java.io.File
import java.time.Instant
import java.time.OffsetDateTime
import java.util.UUID
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class HistoryTest {
    private fun ref(n: Int) = UUID(0, n.toLong()).toString()
    private val start = Instant.parse("2026-10-12T10:00:00Z")
    private fun row(n: Int) = HistoryUsage(ref(n), ref(100), ref(200), "רכב", "מרק", start, start.plusSeconds(60))
    private class Gateway : HistoryGateway {
        val pages = mutableListOf<Triple<String, HistoryFilters, String?>>()
        var vehicleCalls = 0
        var pageAction: suspend (String?) -> HistoryPage = { HistoryPage(emptyList(), false, null) }
        var vehicleAction: suspend () -> List<FamilyVehicle> = { emptyList() }
        var memberAction: suspend () -> List<HistoryMember> = { emptyList() }
        override suspend fun page(owner: String, filters: HistoryFilters, cursor: String?): HistoryPage {
            pages += Triple(owner, filters, cursor)
            return pageAction(cursor)
        }
        override suspend fun vehicles(owner: String): List<FamilyVehicle> { vehicleCalls++; return vehicleAction() }
        override suspend fun members(owner: String) = memberAction()
    }
    private suspend fun settle() { repeat(6) { yield() } }
    private fun vm(api: Gateway, scope: CoroutineScope, identity: () -> HistoryIdentity? = { HistoryIdentity("A", 11) },
                   signals: Flow<BroadcastSignal> = flow { awaitCancellation() }) =
        HistoryViewModel(api, identity, { signals }, scope)

    @Test fun initialsHandleShortBlankWhitespaceAndUnicode() {
        assertEquals("מר", historyInitials(" מרק לוי "))
        assertEquals("דר", historyInitials("דריה")); assertEquals("מי", historyInitials("מיכאל"))
        assertEquals("א", historyInitials("א")); assertEquals("", historyInitials(" \t"))
        assertEquals("𐐀א", historyInitials("𐐀אב"))
    }
    @Test fun availableRequiresSuccessfulKnownState() {
        assertFalse(CurrentVehicleState().allAvailable)
        assertFalse(CurrentVehicleState(CurrentUseStatus.UNAVAILABLE).allAvailable)
        assertTrue(CurrentVehicleState(CurrentUseStatus.READY).allAvailable)
        val vehicles = (1..2).map { FamilyVehicle(ref(it), "רכב", true, "מרק", start.plusSeconds(it.toLong())) }
        val current = CurrentVehicleState(CurrentUseStatus.READY, vehicles)
        assertFalse(current.allAvailable); assertEquals(vehicles, current.occupied)
    }
    @Test fun firstPageAppendDedupeAndEnd() = runBlocking {
        val api = Gateway().apply { pageAction = { cursor ->
            if (cursor == null) HistoryPage(listOf(row(1), row(2)), true, ref(2))
            else HistoryPage(listOf(row(2), row(3)), false, null)
        } }
        val model = vm(api, this)
        try {
            model.start(); settle(); assertEquals(2, model.state.rows.size)
            model.nextPage(); model.nextPage(); settle()
            assertEquals(listOf(ref(1), ref(2), ref(3)), model.state.rows.map { it.sessionRef })
            assertEquals(ref(2), api.pages.last().third)
            model.nextPage(); settle(); assertEquals(2, api.pages.size)
        } finally { model.stop() }
    }
    @Test fun pageFailurePreservesRowsAndNeedsExplicitRetry() = runBlocking {
        val api = Gateway().apply { pageAction = { cursor ->
            if (cursor == null) HistoryPage(listOf(row(1)), true, ref(1)) else error("test")
        } }
        val model = vm(api, this)
        try {
            model.start(); settle(); model.nextPage(); settle()
            assertTrue(model.state.pageError); assertEquals(listOf(row(1)), model.state.rows)
            model.nextPage(); settle(); assertEquals(2, api.pages.size)
            api.pageAction = { HistoryPage(listOf(row(2)), false, null) }
            model.retryPage(); settle(); assertEquals(2, model.state.rows.size)
        } finally { model.stop() }
    }
    @Test fun repeatedCursorFailsWithoutRequestStorm() = runBlocking {
        val api = Gateway().apply { pageAction = { HistoryPage(listOf(row(1)), true, ref(1)) } }
        val model = vm(api, this)
        try {
            model.start(); settle(); model.nextPage(); settle(); assertTrue(model.state.pageError)
            model.nextPage(); settle(); assertEquals(2, api.pages.size)
        } finally { model.stop() }
    }
    @Test fun draftApplyDismissClearAndInvalidRange() = runBlocking {
        val api = Gateway()
        val model = vm(api, this)
        try {
            model.start(); settle(); model.openFilters()
            model.editDraft(HistoryFilters(vehicleRef = ref(100)))
            assertTrue(model.state.applied.empty); assertEquals(1, api.pages.size)
            model.dismissFilters(); assertTrue(model.state.draft.empty)
            model.openFilters(); model.editDraft(HistoryFilters(memberRef = ref(200)))
            model.applyFilters(); settle(); assertFalse(model.state.sheet)
            assertEquals(ref(200), api.pages.last().second.memberRef)
            model.openFilters(); model.editDraft(HistoryFilters(from = OffsetDateTime.parse("2026-10-12T12:00:00Z"),
                to = OffsetDateTime.parse("2026-10-12T11:00:00Z")))
            model.applyFilters(); assertTrue(model.state.rangeError); assertEquals(2, api.pages.size)
            model.clearFilters(); settle()
            assertTrue(model.state.draft.empty && model.state.applied.empty)
            assertEquals(3, api.pages.size)
        } finally { model.stop() }
    }
    @Test fun oldFilterResponseCannotMergeIntoNewResults() = runBlocking {
        val old = CompletableDeferred<HistoryPage>()
        val api = Gateway().apply { pageAction = { withContext(NonCancellable) { old.await() } } }
        val model = vm(api, this)
        try {
            model.start(); settle()
            api.pageAction = { HistoryPage(listOf(row(2)), false, null) }
            model.editDraft(HistoryFilters(vehicleRef = ref(100))); model.applyFilters(); settle()
            old.complete(HistoryPage(listOf(row(1)), false, null)); settle()
            assertEquals(listOf(row(2)), model.state.rows)
        } finally { old.complete(HistoryPage(emptyList(), false, null)); model.stop() }
    }
    @Test fun oldOwnerOrFamilyResponsesAreIgnored() = runBlocking {
        for (next in listOf(HistoryIdentity("B", 11), HistoryIdentity("A", 22))) {
            var identity = HistoryIdentity("A", 11)
            val old = CompletableDeferred<HistoryPage>()
            val api = Gateway().apply { pageAction = { withContext(NonCancellable) { old.await() } } }
            val model = vm(api, this, { identity })
            try {
                model.start(); settle(); identity = next
                api.pageAction = { HistoryPage(listOf(row(2)), false, null) }
                model.start(); settle(); old.complete(HistoryPage(listOf(row(1)), false, null)); settle()
                assertEquals(listOf(row(2)), model.state.rows)
                assertEquals(next.owner, api.pages.last().first)
            } finally { old.complete(HistoryPage(emptyList(), false, null)); model.stop() }
        }
    }
    @Test fun realtimeRefreshesOnlyCurrentStateAndDisconnectIsUnknown() = runBlocking {
        val signals = MutableSharedFlow<BroadcastSignal>(extraBufferCapacity = 10)
        val api = Gateway().apply { pageAction = { HistoryPage(listOf(row(1)), false, null) } }
        val model = vm(api, this, signals = signals)
        try {
            model.start(); settle(); signals.emit(BroadcastSignal.SUBSCRIBED); settle()
            assertTrue(model.state.current.allAvailable)
            api.vehicleAction = { listOf(FamilyVehicle(ref(100), "רכב", true, "מרק", start)) }
            signals.emit(BroadcastSignal.INVALIDATED); settle()
            assertEquals(1, model.state.current.occupied.size); assertEquals(1, api.pages.size)
            signals.emit(BroadcastSignal.DISCONNECTED); settle(); assertFalse(model.state.current.allAvailable)
            assertEquals(listOf(row(1)), model.state.rows)
            signals.emit(BroadcastSignal.SUBSCRIBED); settle()
            assertEquals(CurrentUseStatus.READY, model.state.current.status)
        } finally { model.stop() }
    }
    @Test fun apiAndMemberFailureAreSeparateFromHistory() = runBlocking {
        val api = Gateway().apply {
            pageAction = { HistoryPage(listOf(row(1)), false, null) }
            vehicleAction = { error("test") }; memberAction = { error("test") }
        }
        val model = vm(api, this)
        try {
            model.start(); settle(); assertFalse(model.state.current.allAvailable)
            assertEquals(CurrentUseStatus.UNAVAILABLE, model.state.current.status)
            assertTrue(model.state.optionsError); assertFalse(model.state.pageError)
            assertEquals(1, model.state.rows.size)
        } finally { model.stop() }
    }
    @Test fun invalidationDuringInFlightReadLeavesOneFollowupAndStopCancelsSubscription() = runBlocking {
        val wait = CompletableDeferred<List<FamilyVehicle>>()
        var cancelled = false
        val signal = MutableSharedFlow<BroadcastSignal>(extraBufferCapacity = 10)
        val stream = flow { try { emitAll(signal) } finally { cancelled = true } }
        val api = Gateway().apply { vehicleAction = { wait.await() } }
        val model = vm(api, this, signals = stream)
        try {
            model.start(); settle(); repeat(3) { signal.emit(BroadcastSignal.INVALIDATED) }; settle()
            assertEquals(1, api.vehicleCalls)
            wait.complete(emptyList()); settle(); assertEquals(2, api.vehicleCalls)
            model.stop(); settle(); assertTrue(cancelled); assertTrue(model.state.rows.isEmpty())
        } finally { model.stop() }
    }
    @Test fun combinedQueryUsesOnlyPublicFiltersAndOffsetAwareValues() {
        val f = HistoryFilters(ref(100), ref(200), OffsetDateTime.parse("2026-10-12T12:34:00+03:00"),
            OffsetDateTime.parse("2026-10-12T13:34:00+03:00"))
        val path = URLDecoder.decode(HistoryApi.path(f, ref(1)), "UTF-8")
        assertTrue(path.startsWith("/api/car/history?limit=50"))
        assertTrue(path.contains("vehicle_ref=${ref(100)}")); assertTrue(path.contains("member_ref=${ref(200)}"))
        assertTrue(path.contains("cursor=${ref(1)}")); assertTrue(path.contains("from_datetime=${f.from}"))
        assertTrue(path.contains("to_datetime=${f.to}")); assertFalse(path.contains("family_id"))
    }
    @Test fun strictVehicleParsingRejectsMissingTimestampAndMalformedAvailability() {
        val obj = JSONObject().put("vehicle_ref", ref(100)).put("display_name", "רכב")
            .put("retired_at", JSONObject.NULL).put("in_use", false).put("current_driver", JSONObject.NULL)
            .put("started_at", JSONObject.NULL)
        assertFalse(HistoryApi.parseVehicles(JSONArray().put(obj).toString()).single().inUse)
        obj.put("in_use", true).put("current_driver", "מרק").put("started_at", "2026-10-12T13:00:00+03:00")
        assertEquals(start, HistoryApi.parseVehicles(JSONArray().put(obj).toString()).single().startedAt)
        obj.remove("started_at")
        assertTrue(runCatching { HistoryApi.parseVehicles(JSONArray().put(obj).toString()) }.isFailure)
        assertTrue(runCatching { HistoryApi.parseVehicles("{}") }.isFailure)
    }
    @Test fun pageAndMemberParserPreservePublicIdentity() {
        val row = JSONObject().put("session_ref", ref(1)).put("vehicle_ref", ref(100)).put("member_ref", ref(200))
            .put("vehicle_name", "רכב").put("name", "מרק").put("started_at", start.toString())
            .put("ended_at", start.plusSeconds(60).toString())
        val body = JSONObject().put("recent_usage", JSONArray().put(row)).put("has_more", true).put("next_cursor", ref(1))
        assertEquals(ref(1), HistoryApi.parsePage(body.toString()).rows.single().sessionRef)
        body.put("next_cursor", JSONObject.NULL)
        assertTrue(runCatching { HistoryApi.parsePage(body.toString()) }.isFailure)
        val members = JSONObject().put("members", JSONArray().put(JSONObject().put("member_ref", ref(200)).put("name", "מרק")))
        assertEquals(ref(200), HistoryApi.parseMembers(members.toString()).single().ref)
    }
    @Test fun reservedSlotAndPaginationThresholdAndExistingBack() {
        assertEquals(40, HISTORY_ILLUSTRATION_SLOT_DP)
        assertFalse(historyNearEnd(ref(1), (1..5).map(::row)))
        assertTrue(historyNearEnd(ref(3), (1..5).map(::row)))
        val shell = AppShellState(); shell.select(AppMode.DASHBOARD); shell.openCategory(DashboardCategory.HISTORY)
        shell.back(); assertNull(shell.category); assertEquals(AppMode.DASHBOARD, shell.mode)
    }
    @Test fun exactAssetsBlankSlotAndHistoryOnlySliderGate() {
        val ui = File("src/main/java/il/fca/companion/ui/HistoryScreen.kt").readText()
        for (asset in listOf("fca_header_wordmark", "history_icon", "ic_chevron_back", "ic_filter", "car_icon", "user_icon", "ic_calender"))
            assertTrue(ui.contains("R.drawable.$asset"))
        assertFalse(ui.contains("R.drawable.vehicle_"))
        assertTrue(ui.contains("Spacer(Modifier.size(HISTORY_ILLUSTRATION_SLOT_DP.dp))"))
        assertTrue(ui.contains("items(state.rows, key = { it.sessionRef })"))
        val shell = File("src/main/java/il/fca/companion/ui/AuthenticatedAppShell.kt").readText()
        assertTrue(shell.contains("if (!imeVisible && state.category != DashboardCategory.HISTORY)"))
        assertTrue(shell.contains("HistoryScreen(history, familyId, state::back)"))
    }
    @Test fun staleVehicleReplyAfterFamilyChangeCannotApply() = runBlocking {
        val old = CompletableDeferred<List<FamilyVehicle>>()
        var identity = HistoryIdentity("A", 11)
        val api = Gateway().apply { vehicleAction = { withContext(NonCancellable) { old.await() } } }
        val model = vm(api, this, { identity })
        try {
            model.start(); settle(); identity = HistoryIdentity("A", 22)
            api.vehicleAction = { emptyList() }; model.start(); settle()
            old.complete(listOf(FamilyVehicle(ref(100), "Old", true, "Old", start))); settle()
            assertTrue(model.state.current.allAvailable); assertTrue(model.state.vehicleOptions.isEmpty())
        } finally { old.complete(emptyList()); model.stop() }
    }
    @Test fun disconnectDuringCurrentReadCannotPublishAvailable() = runBlocking {
        val wait = CompletableDeferred<List<FamilyVehicle>>()
        val signals = MutableSharedFlow<BroadcastSignal>(extraBufferCapacity = 10)
        val api = Gateway().apply { vehicleAction = { wait.await() } }
        val model = vm(api, this, signals = signals)
        try {
            model.start(); settle(); signals.emit(BroadcastSignal.DISCONNECTED); settle()
            wait.complete(emptyList()); settle(); assertFalse(model.state.current.allAvailable)
            assertEquals(CurrentUseStatus.UNAVAILABLE, model.state.current.status)
        } finally { model.stop() }
    }
}

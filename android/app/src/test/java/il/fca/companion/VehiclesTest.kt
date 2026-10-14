package il.fca.companion

import android.app.Application
import il.fca.companion.net.*
import il.fca.companion.ui.*
import java.io.File
import java.io.IOException
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class VehiclesTest {
    private val maker = Manufacturer(1, "יונדאי")
    private fun draft() = VehicleDraft("  רכב !  ", VehicleCategory.SEDAN, maker, maker.name, " דגם/自由 ", " AB- 12 ")
    private fun vehicle(n: Int, retired: Boolean = false) = ManagedVehicle(UUID(0, n.toLong()).toString(), "רכב $n",
        Instant.EPOCH.plusSeconds(n.toLong()), if (retired) Instant.EPOCH else null, null, null, null, null, null)
    private class Gateway : VehiclesGateway {
        var rows = emptyList<ManagedVehicle>(); var admin = true; var catalogs = 0
        val owners = mutableListOf<String>(); val requests = mutableListOf<VehicleSubmission>()
        var list: (suspend () -> List<ManagedVehicle>)? = null
        var catalog: suspend () -> List<Manufacturer> = { listOf(Manufacturer(1, "יונדאי"), Manufacturer(2, "קיה")) }
        var createAction: suspend (VehicleSubmission) -> ManagedVehicle = { error("unexpected create") }
        override suspend fun vehicles(owner: String): List<ManagedVehicle> { owners += owner; return list?.invoke() ?: rows }
        override suspend fun canCreate(owner: String) = admin
        override suspend fun manufacturers(owner: String): List<Manufacturer> { catalogs++; return catalog() }
        override suspend fun create(owner: String, submission: VehicleSubmission): ManagedVehicle {
            owners += owner; requests += submission; return createAction(submission)
        }
    }
    private suspend fun settle() { repeat(8) { yield() } }
    private fun vm(api: Gateway, scope: CoroutineScope, identity: () -> VehiclesIdentity? = { VehiclesIdentity("A", 10) }) =
        VehiclesViewModel(api, identity, scope)

    @Test fun fieldsAreRequiredWithoutNormalizationOrInventedRegex() {
        assertTrue(draft().valid)
        assertFalse(draft().copy(name = " \t").valid); assertFalse(draft().copy(model = " ").valid)
        assertFalse(draft().copy(plate = "").valid); assertFalse(draft().copy(category = null).valid)
        assertFalse(draft().copy(manufacturer = null).valid)
        assertFalse(draft().copy(manufacturerQuery = "arbitrary").valid)
        val request = VehicleSubmission(UUID.randomUUID().toString(), draft()).json()
        assertEquals(draft().name, request.getString("display_name")); assertEquals(draft().plate, request.getString("license_plate"))
        assertEquals(draft().model, request.getString("model")); assertEquals(1, request.getInt("manufacturer_id"))
        assertEquals(6, request.length()); assertEquals(4, UUID.fromString(request.getString("request_id")).version())
        VehicleCategory.entries.forEach { assertEquals(it.wire,
            VehicleSubmission(UUID.randomUUID().toString(), draft().copy(category = it)).json().getString("category")) }
    }
    @Test fun categoryAssetsAreExactAndNullIsNotGuessed() {
        assertEquals(listOf("hatchback", "sedan", "crossover", "minivan", "suv"), VehicleCategory.entries.map { it.wire })
        assertEquals(listOf(R.drawable.vehicle_hatchback, R.drawable.vehicle_sedan, R.drawable.vehicle_crossover,
            R.drawable.vehicle_minivan, R.drawable.vehicle_suv), VehicleCategory.entries.map(::vehicleIllustration))
        assertEquals(R.drawable.single_car_icon, vehicleIllustration(null))
    }
    @Test fun legacyMetadataAndFullMetadataParsing() {
        val obj = JSONObject().put("vehicle_ref", vehicle(1).ref).put("display_name", "legacy")
            .put("created_at", "2026-10-13T10:00:00Z")
        listOf("retired_at", "category", "manufacturer_id", "manufacturer_name_he", "model", "license_plate")
            .forEach { obj.put(it, JSONObject.NULL) }
        assertNull(VehiclesApi.parseVehicle(obj).category)
        obj.put("category", "suv").put("manufacturer_id", 1).put("manufacturer_name_he", "יצרן")
            .put("model", "x").put("license_plate", "custom").put("retired_at", "2026-10-13T11:00:00Z")
        val result = VehiclesApi.parseVehicle(obj)
        assertTrue(result.readOnly); assertEquals(VehicleCategory.SUV, result.category); assertEquals("custom", result.plate)
        assertEquals(listOf(maker), VehiclesApi.parseManufacturers("[{\"id\":1,\"name_he\":\"יונדאי\"}]"))
    }
    @Test fun listPreservesServerCreationOrderAndRetiredReadOnlyNavigation() = runBlocking {
        val api = Gateway().apply { rows = listOf(vehicle(3), vehicle(1, true), vehicle(2)) }
        val model = vm(api, this)
        try {
            model.start(); settle()
            assertEquals(api.rows, model.state.rows); assertEquals(listOf(vehicle(3), vehicle(2)), model.state.active)
            assertEquals(listOf(vehicle(1, true)), model.state.retired); assertTrue(model.state.canCreate)
            for (row in api.rows) {
                model.select(row); assertEquals(VehiclesPage.PLACEHOLDER, model.state.page)
                assertEquals(row.ref, model.state.selected?.ref); assertEquals(row.readOnly, model.state.selected?.readOnly)
                assertTrue(model.back()); settle()
            }
            assertFalse(model.back())
            val shell = AppShellState(); shell.select(AppMode.DASHBOARD); shell.openCategory(DashboardCategory.VEHICLES)
            assertEquals(DashboardCategory.VEHICLES, shell.category); shell.back(); assertNull(shell.category)
        } finally { model.stop() }
    }
    @Test fun emptyNonAdminCannotOpenAddAndNoRetiredSection() = runBlocking {
        val model = vm(Gateway().apply { admin = false }, this)
        try {
            model.start(); settle(); assertTrue(model.state.loaded); assertTrue(model.state.rows.isEmpty())
            assertTrue(model.state.retired.isEmpty()); assertFalse(model.state.canCreate)
            model.add(); assertEquals(VehiclesPage.LIST, model.state.page)
        } finally { model.stop() }
    }
    @Test fun catalogLoadsOnceFiltersLocallyAndRequiresSelection() = runBlocking {
        val api = Gateway(); val model = vm(api, this)
        try {
            model.start(); settle(); model.add(); assertTrue(model.state.catalogLoading); settle()
            model.edit(draft()); model.queryManufacturer("יונ")
            assertNull(model.state.draft.manufacturer); assertFalse(model.state.draft.valid)
            assertEquals(listOf(maker), model.state.matchingManufacturers)
            model.chooseManufacturer(Manufacturer(99, "fake")); assertNull(model.state.draft.manufacturer)
            model.chooseManufacturer(maker); assertTrue(model.state.draft.valid)
            model.queryManufacturer("none"); assertTrue(model.state.matchingManufacturers.isEmpty())
            model.back(); settle(); model.add(); settle(); assertEquals(1, api.catalogs)
            assertEquals(VehicleDraft(), model.state.draft)
        } finally { model.stop() }
    }
    @Test fun catalogFailureHasExplicitRetry() = runBlocking {
        val api = Gateway().apply { catalog = { throw IOException() } }; val model = vm(api, this)
        try {
            model.start(); settle(); model.add(); settle(); assertTrue(model.state.catalogError)
            api.catalog = { listOf(maker) }; model.loadManufacturers(); settle()
            assertTrue(model.state.catalogLoaded); assertFalse(model.state.catalogError); assertEquals(2, api.catalogs)
        } finally { model.stop() }
    }
    @Test fun failedSubmissionLocksExactPayloadAndRetryIdentityThenRefreshesList() = runBlocking {
        val api = Gateway().apply { createAction = { throw IOException() } }; val model = vm(api, this)
        try {
            model.start(); settle(); model.add(); settle(); model.edit(draft()); model.submit()
            assertTrue(model.state.submitting); model.submit(); settle()
            assertEquals(1, api.requests.size); assertNotNull(model.state.submitError)
            val pending = model.state.pending
            model.edit(draft().copy(name = "changed")); assertEquals(draft(), model.state.draft)
            api.createAction = { api.rows = listOf(vehicle(1)); vehicle(1) }
            model.submit(); settle()
            assertSame(pending, api.requests.last()); assertEquals(api.requests.first().json().toString(), api.requests.last().json().toString())
            assertEquals(VehiclesPage.LIST, model.state.page); assertNull(model.state.pending)
            assertEquals(api.rows, model.state.rows); assertTrue(api.owners.all { it == "A" })
        } finally { model.stop() }
    }
    @Test fun forbiddenIsNormalErrorAndBackDiscardsDraft() = runBlocking {
        val api = Gateway().apply { createAction = { throw HttpFailure(403) } }; val model = vm(api, this)
        try {
            model.start(); settle(); model.add(); settle(); model.edit(draft()); model.submit(); settle()
            assertEquals("אין הרשאה להוספת רכב", model.state.submitError)
            assertTrue(model.back()); assertEquals(VehicleDraft(), model.state.draft); assertNull(model.state.pending)
        } finally { model.stop() }
    }
    @Test fun lateCreationAfterBackCannotReplaceNewDraftAndStartIsIdempotent() = runBlocking {
        val gate = CompletableDeferred<Unit>()
        val api = Gateway().apply { createAction = { withContext(NonCancellable) { gate.await(); vehicle(1) } } }
        val model = vm(api, this)
        try {
            model.start(); settle(); model.add(); settle(); model.edit(draft()); model.submit(); settle()
            val pending = model.state.pending
            model.start(); assertSame(pending, model.state.pending)
            model.back(); settle(); model.add(); model.edit(draft().copy(name = "new draft"))
            gate.complete(Unit); settle()
            assertEquals(VehiclesPage.ADD, model.state.page); assertEquals("new draft", model.state.draft.name)
            assertNull(model.state.pending); assertEquals(1, api.requests.size)
        } finally { gate.complete(Unit); model.stop() }
    }
    @Test fun listFailureIsNotReportedAsEmptyAndCanRetry() = runBlocking {
        val api = Gateway().apply { list = { throw IOException() } }; val model = vm(api, this)
        try {
            model.start(); settle(); assertTrue(model.state.loadError); assertFalse(model.state.loaded)
            assertFalse(model.state.canCreate)
            api.list = null; model.refresh(); settle()
            assertTrue(model.state.loaded); assertFalse(model.state.loadError); assertTrue(model.state.canCreate)
        } finally { model.stop() }
    }
    @Test fun staleOwnerOrFamilyResponseCannotApply() = runBlocking {
        var identity = VehiclesIdentity("A", 10)
        val gate = CompletableDeferred<Unit>()
        val api = Gateway().apply { list = { withContext(NonCancellable) { gate.await(); listOf(vehicle(1)) } } }
        val model = vm(api, this) { identity }
        try {
            model.start(); settle(); identity = VehiclesIdentity("A", 11)
            gate.complete(Unit); settle(); assertTrue(model.state.rows.isEmpty())
            model.stop(); api.list = null; identity = VehiclesIdentity("B", 11); model.start(); settle()
            assertTrue(model.state.rows.isEmpty()); assertEquals("B", api.owners.last())
        } finally { gate.complete(Unit); model.stop() }
    }
    @Test fun sourceVisualContractsAndFrozenScreensIntegration() {
        val ui = File("src/main/java/il/fca/companion/ui/VehiclesScreen.kt").readText()
        assertTrue(ui.contains("AbsoluteAlignment.CenterRight")); assertTrue(ui.contains("if (state.canCreate)"))
        assertTrue(ui.contains("if (state.retired.isNotEmpty())")); assertTrue(ui.contains("alpha(if (vehicle.readOnly) .5f else 1f)"))
        val card = ui.substringAfter("private fun VehicleCard")
        listOf("manufacturer", "plate", "inUse", "driver", "model").forEach { assertFalse(card.contains(it)) }
        assertTrue(card.contains("clickable(onClick = open)"))
        val shell = File("src/main/java/il/fca/companion/ui/AuthenticatedAppShell.kt").readText()
        assertTrue(shell.contains("VehiclesScreen(vehicles, familyId, state::back)"))
        assertTrue(shell.contains("state.category != DashboardCategory.VEHICLES"))
    }
    @Test fun emptyStateUsesHistoryHeaderTreatmentAndAdminOnlyCopy() {
        val ui = File("src/main/java/il/fca/companion/ui/VehiclesScreen.kt").readText()
        val header = ui.substringAfter("internal fun VehiclesHeader").substringBefore("private fun VehicleCard")
        assertTrue(header.contains("compositingStrategy = CompositingStrategy.Offscreen"))
        assertTrue(header.contains("blendMode = BlendMode.Multiply"))
        assertTrue(header.contains("AbsoluteAlignment.CenterRight"))
        val title = header.substringAfter("if (title == \"רכבים\")").substringBefore("} else Row")
        assertTrue(title.contains("R.drawable.vehicles_icon"))
        assertTrue(title.contains("requiredSize(200.dp)"))
        assertFalse(title.contains("Text("))
        val empty = ui.substringAfter("state.loaded && state.rows.isEmpty()").substringBefore("else -> LazyColumn")
        assertTrue(empty.contains("R.drawable.no_cars_icon"))
        assertTrue(empty.substringBefore("if (state.canCreate)").contains("אין עדיין רכבים"))
        val admin = empty.substringAfter("if (state.canCreate)").substringBefore("} else {")
        assertTrue(admin.contains("הוסיפו את הרכב הראשון של המשפחה\\nכדי להתחיל לנהל אותו כאן"))
        assertTrue(admin.contains("זמין למנהל המשפחה בלבד"))
        assertTrue(admin.contains("OutlinedButton(onClick = model::add"))
    }
    @Test fun vehiclesPolishPreservesAdminAndUsesNonScrollableFiveOptionRow() {
        val ui = File("src/main/java/il/fca/companion/ui/VehiclesScreen.kt").readText()
        val empty = ui.substringAfter("state.loaded && state.rows.isEmpty()").substringBefore("else -> LazyColumn")
        val nonAdmin = empty.substringAfter("} else {")
        assertTrue(nonAdmin.contains("כרגע אין רכבים במשפחה\\nרק מנהל המשפחה יכול להוסיף רכבים"))
        assertFalse(nonAdmin.contains("Button(")); assertFalse(nonAdmin.contains("model::add"))
        val addTitle = ui.substringAfter("} else Row").substringBefore("private fun VehicleCard")
        assertTrue(addTitle.contains("R.drawable.single_car_icon"))
        val add = File("src/main/java/il/fca/companion/ui/AddVehicleScreen.kt").readText()
        val categories = add.substringAfter("Text(\"סוג רכב\"").substringBefore("VehicleField(\"יצרן\"")
        assertTrue(categories.contains("VehicleCategory.entries.forEach"))
        assertTrue(categories.contains("Modifier.weight(1f)"))
        assertFalse(categories.contains("horizontalScroll"))
        assertEquals(5, VehicleCategory.entries.size)
        assertTrue(add.contains("showManufacturerSuggestions(draft.manufacturerQuery, draft.manufacturer)"))
    }
    @Test fun manufacturerSuggestionsRequireTypingAndHideAfterSelectionOrClearing() = runBlocking {
        val api = Gateway(); val model = vm(api, this)
        fun visible() = showManufacturerSuggestions(model.state.draft.manufacturerQuery, model.state.draft.manufacturer)
        try {
            model.start(); settle(); model.add(); settle(); assertFalse(visible())
            model.queryManufacturer("יו"); assertTrue(visible()); assertEquals(listOf(maker), model.state.matchingManufacturers)
            model.chooseManufacturer(maker); assertFalse(visible()); assertEquals(maker, model.state.draft.manufacturer)
            model.queryManufacturer("missing"); assertTrue(visible()); assertTrue(model.state.matchingManufacturers.isEmpty())
            model.queryManufacturer(""); assertFalse(visible())
            model.queryManufacturer("  "); assertFalse(visible()); assertEquals(1, api.catalogs)
        } finally { model.stop() }
    }
}

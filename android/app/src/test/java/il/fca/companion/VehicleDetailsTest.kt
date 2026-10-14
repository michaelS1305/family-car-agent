package il.fca.companion

import android.app.Application
import il.fca.companion.net.*
import il.fca.companion.ui.*
import java.io.File
import java.io.IOException
import java.time.Instant
import java.time.LocalDate
import java.util.UUID
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class VehicleDetailsTest {
    private val ref = UUID(0, 1).toString()
    private val maker = Manufacturer(1, "יונדאי")
    private fun vehicle(retired: Boolean = false) = ManagedVehicle(ref, "יונדאי", Instant.EPOCH,
        if (retired) Instant.EPOCH else null, VehicleCategory.HATCHBACK, 1, maker.name, "i20", "ABC-12")
    private inner class Gateway : VehicleDetailsGateway {
        var row = VehicleDetail(vehicle(), false)
        var admin = true
        var rows = emptyList<VehicleMaintenance>()
        var catalogs = 0
        var detailAction: (suspend () -> VehicleDetail)? = null
        var failure: Exception? = null
        val calls = mutableListOf<Pair<String, String>>()
        var edits = 0; var retires = 0; var additions = 0
        override suspend fun detail(owner: String, ref: String): VehicleDetail {
            calls += owner to ref; return detailAction?.invoke() ?: row
        }
        override suspend fun maintenance(owner: String, ref: String) = rows
        override suspend fun canManage(owner: String) = admin
        override suspend fun manufacturers(owner: String): List<Manufacturer> { catalogs++; return listOf(maker) }
        override suspend fun edit(owner: String, ref: String, draft: VehicleDraft) {
            failure?.let { throw it }; edits++
            row = row.copy(vehicle = row.vehicle.copy(name = draft.name, category = draft.category,
                manufacturerId = draft.manufacturer!!.id, manufacturerName = draft.manufacturer.name, model = draft.model, plate = draft.plate))
        }
        override suspend fun retire(owner: String, ref: String) {
            failure?.let { throw it }; retires++; row = row.copy(vehicle = vehicle(true))
        }
        override suspend fun addMaintenance(owner: String, ref: String, description: String, date: LocalDate) {
            failure?.let { throw it }; additions++
            rows = rows + VehicleMaintenance(UUID(0, additions.toLong()).toString(), description, date)
        }
    }
    private suspend fun settle() { repeat(12) { yield() } }
    private fun model(g: Gateway, scope: CoroutineScope, identity: () -> VehiclesIdentity? = { VehiclesIdentity("owner", 1) }) =
        VehicleDetailsViewModel(g, ref, identity, scope)

    @Test fun statusAndMetadataAreCanonical() {
        assertEquals("פנוי", VehicleDetail(vehicle(), false).status)
        assertEquals("בשימוש", VehicleDetail(vehicle(), true).status)
        assertEquals("לא פעיל", VehicleDetail(vehicle(true), true).status)
        assertEquals(R.drawable.single_car_icon, vehicleIllustration(null))
        assertEquals("יונדאי", vehicle().manufacturerName)
        assertEquals("i20", vehicle().model); assertEquals("ABC-12", vehicle().plate)
    }
    @Test fun roleAndRetiredGuardsApplyToAllManagementForms() = runBlocking {
        for ((admin, retired) in listOf(true to false, false to false, true to true)) {
            val g = Gateway().apply { this.admin = admin; row = row.copy(vehicle = vehicle(retired)) }
            val m = model(g, this)
            try {
                m.start(); settle(); assertEquals(admin && !retired, m.state.canManage)
                VehicleDialog.entries.forEach { d -> m.open(d); assertEquals(if (admin && !retired) d else null, m.state.dialog); m.close() }
                assertEquals(0, g.retires); assertEquals(0, g.additions)
            } finally { m.stop() }
        }
    }
    @Test fun loadFailureNeverBecomesAvailableAndRetries() = runBlocking {
        val g = Gateway().apply { detailAction = { throw IOException() } }; val m = model(g, this)
        try {
            m.start(); settle(); assertTrue(m.state.error); assertNull(m.state.detail); assertFalse(m.state.canManage)
            g.detailAction = null; m.refresh(); settle(); assertEquals("פנוי", m.state.detail!!.status)
        } finally { m.stop() }
    }
    @Test fun editPrefillCatalogAndFailurePreservation() = runBlocking {
        val g = Gateway(); val m = model(g, this)
        try {
            m.start(); settle(); m.open(VehicleDialog.EDIT); settle()
            assertEquals("i20", m.state.draft.model); assertEquals(maker, m.state.draft.manufacturer)
            m.query(""); assertFalse(showManufacturerSuggestions(m.state.draft.manufacturerQuery, m.state.draft.manufacturer))
            assertFalse(m.state.draft.valid)
            m.query("יונ"); assertEquals(listOf(maker), m.state.matches)
            m.choose(maker); m.edit(m.state.draft.copy(name = "חדש"))
            g.failure = HttpFailure(403); m.submit(); settle()
            assertNotNull(m.state.operationError); assertEquals("חדש", m.state.draft.name); assertEquals(VehicleDialog.EDIT, m.state.dialog)
            g.failure = null; m.submit(); settle(); assertEquals("חדש", m.state.detail!!.vehicle.name); assertNull(m.state.dialog)
            m.open(VehicleDialog.EDIT); settle(); assertEquals(1, g.catalogs)
            val body = VehicleDetailsApi.editBody(m.state.draft)
            assertEquals(setOf("display_name", "category", "manufacturer_id", "model", "license_plate"), body.keys().asSequence().toSet())
        } finally { m.stop() }
    }
    @Test fun maintenancePreservesOrderPastDatesAndFailedDraft() = runBlocking {
        val g = Gateway(); val m = model(g, this)
        try {
            m.start(); settle(); assertTrue(m.state.maintenance.isEmpty())
            m.open(VehicleDialog.MAINTENANCE)
            m.maintenanceDraft("טיפול", LocalDate.of(2020, 1, 2))
            g.failure = IOException(); m.submit(); settle()
            assertEquals("טיפול", m.state.description); assertNotNull(m.state.operationError); assertEquals(0, g.additions)
            g.failure = null; m.submit(); settle()
            assertNull(m.state.dialog); assertEquals(LocalDate.of(2020, 1, 2), m.state.maintenance.single().date)
            g.rows = g.rows + VehicleMaintenance(UUID(0, 20).toString(), "ישן", LocalDate.of(2019, 1, 1))
            m.refreshMaintenance(); settle(); assertEquals(g.rows, m.state.maintenance)
        } finally { m.stop() }
    }
    @Test fun retireCancelConflictAndSuccessKeepSameDetail() = runBlocking {
        val g = Gateway(); val m = model(g, this)
        try {
            m.start(); settle(); m.open(VehicleDialog.RETIRE); m.close(); assertEquals(0, g.retires)
            m.open(VehicleDialog.RETIRE); g.failure = HttpFailure(409); m.submit(); settle()
            assertNotNull(m.state.operationError); assertFalse(m.state.detail!!.vehicle.readOnly)
            g.failure = null; m.submit(); settle()
            assertEquals(ref, m.state.detail!!.vehicle.ref); assertTrue(m.state.detail!!.vehicle.readOnly); assertFalse(m.state.canManage)
        } finally { m.stop() }
    }
    @Test fun oldOwnerResponseCannotApply() = runBlocking {
        val g = Gateway(); val gate = CompletableDeferred<Unit>()
        var who: VehiclesIdentity? = VehiclesIdentity("owner", 1)
        g.detailAction = { withContext(NonCancellable) { gate.await(); g.row } }
        val m = model(g, this) { who }
        try {
            m.start(); yield(); who = VehiclesIdentity("another", 2); gate.complete(Unit); settle()
            assertNull(m.state.detail); assertFalse(m.state.canManage)
            assertEquals(listOf("owner" to ref), g.calls)
        } finally { gate.complete(Unit); m.stop() }
    }
    @Test fun companionUsesEvidenceAndUnknownNeverBecomesBroken() {
        fun snapshot(device: DeviceHealth = DeviceHealth.REGISTERED, local: Boolean = true,
            binding: Boolean? = true, system: Boolean? = true, location: Boolean = true) =
            companionPresentation(device, local, binding, system, true, location, true, "Hyundai Audio", observationVerified = true)
        assertEquals(CompanionHealth.READY, snapshot().health)
        assertEquals("Hyundai Audio", snapshot().friendlyName)
        assertEquals(CompanionHealth.SETUP, snapshot(device = DeviceHealth.MISSING).health)
        assertEquals(CompanionHealth.SETUP, snapshot(local = false).health)
        assertEquals(CompanionHealth.UNKNOWN, snapshot(device = DeviceHealth.UNKNOWN).health)
        assertEquals(CompanionHealth.UNKNOWN, snapshot(binding = null).health)
        assertEquals(CompanionHealth.ACTION, snapshot(system = false).health)
        assertEquals(CompanionHealth.ACTION, snapshot(device = DeviceHealth.INVALID).health)
        assertEquals(CompanionHealth.SETUP, snapshot(location = false).health)
        assertEquals("לא פעיל", CompanionPresentation(CompanionHealth.RETIRED).summary)
        assertEquals(CompanionHealth.UNKNOWN, companionPresentation(DeviceHealth.REGISTERED, true, true, true,
            true, true, true, "Hyundai Audio").health)
    }
    @Test fun productSourcesProtectNavigationPrivacyAndAssets() {
        val ui = File("src/main/java/il/fca/companion/ui/VehicleDetailsScreen.kt").readText()
        assertTrue(ui.contains("AbsoluteAlignment.CenterRight"))
        assertTrue(ui.contains("R.drawable.fca_header_wordmark"))
        assertTrue(ui.contains("if (s.canManage)")); assertTrue(ui.contains("if (!v.readOnly)"))
        listOf("current_driver", "started_at", "device_ref", "companionId").forEach { assertFalse(ui.contains(it)) }
        val companion = File("src/main/java/il/fca/companion/ui/CompanionScreen.kt").readText()
        listOf("address", "device_ref", "companionId", "UUID").forEach { assertFalse(companion.contains(it)) }
        assertTrue(companion.contains("RadioButton(choice.selected"))
        val main = File("src/main/java/il/fca/companion/MainActivity.kt").readText()
        assertTrue(main.contains("override fun onNewIntent"))
        assertTrue(main.contains("else choosePaired(owner, vehicle)"))
        val activate = main.substringAfter("private fun activate")
        assertTrue(activate.indexOf("\"PUT\"") < activate.indexOf("app.store.associate"))
        assertTrue(activate.indexOf("app.store.associate") < activate.indexOf("DetectorPlatform.start"))
        assertTrue(BluetoothChoice("Hyundai Audio", true).selected)
    }
}

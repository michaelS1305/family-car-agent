package il.fca.companion

import android.app.Application
import il.fca.companion.ui.*
import il.fca.companion.net.ManagedVehicle
import java.time.Instant
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class FirstVehicleSetupTest {
    private val who = VehiclesIdentity("owner", 1)
    private val empty = VehiclesState(loaded = true, canCreate = true)
    private fun state() = FirstVehicleSetupState().apply { restoreOnce(null); activate(who) }

    @Test fun onlyAuthoritativeEmptyManagerIsEligible() {
        val s = state()
        assertTrue(s.visible(who, empty))
        assertFalse(s.visible(null, empty))
        assertFalse(s.visible(who, VehiclesState()))
        assertFalse(s.visible(who, empty.copy(loading = true)))
        assertFalse(s.visible(who, empty.copy(loadError = true)))
        assertFalse(s.visible(who, empty.copy(canCreate = false)))
        assertFalse(s.visible(who, empty.copy(loaded = false)))
        assertFalse(s.visible(who, empty.copy(page = VehiclesPage.ADD)))
    }
    @Test fun failureDoesNotPreventLaterAuthoritativeCheck() {
        val s = state()
        s.observe(who, empty.copy(loadError = true))
        assertTrue(s.visible(who, empty))
    }
    @Test fun dismissalSurvivesRepeatedActivationAndSavedTaskRestoration() {
        val s = state()
        assertTrue(s.dismiss(who)); assertFalse(s.dismiss(who))
        repeat(3) { s.activate(who); assertFalse(s.visible(who, empty)) }
        val restored = FirstVehicleSetupState().apply { restoreOnce(s.save()); activate(who) }
        assertFalse(restored.visible(who, empty))
        restored.restoreOnce(null)
        assertFalse(restored.visible(who, empty))
        assertTrue(state().visible(who, empty))
    }
    @Test fun restorationDoesNotSaveEligibilityOrServerData() {
        val s = state()
        val restored = FirstVehicleSetupState().apply { restoreOnce(s.save()); activate(who) }
        assertFalse(restored.visible(who, VehiclesState()))
        assertTrue(restored.visible(who, empty))
        assertEquals(setOf("identity", "handled"), s.save().keySet())
        assertFalse(s.save().getString("identity")!!.contains("owner"))
    }
    @Test fun logoutAccountAndFamilyChangesDoNotShareDismissal() {
        val s = state(); s.dismiss(who)
        val other = VehiclesIdentity("other", 1)
        assertFalse(s.visible(other, empty)); s.activate(other)
        assertTrue(s.visible(other, empty)); assertFalse(s.visible(who, empty))
        s.dismiss(other)
        val family = other.copy(family = 2); s.activate(family)
        assertTrue(s.visible(family, empty))
        s.clear(); assertFalse(s.visible(family, empty))
        s.activate(who); assertTrue(s.visible(who, empty))
    }
    @Test fun activeAndRetiredVehiclesCountAndPreventReappearance() {
        for (retired in listOf(false, true)) {
            val s = state()
            val row = ManagedVehicle("vehicle", "car", Instant.EPOCH,
                if (retired) Instant.EPOCH else null, null, null, null, null, null)
            val populated = empty.copy(rows = listOf(row))
            assertFalse(s.visible(who, populated)); s.observe(who, populated)
            assertFalse(s.visible(who, empty))
        }
    }
    @Test fun setupNavigatesToNormalVehiclesWithoutCompanionHint() {
        val shell = AppShellState()
        shell.openFirstVehicleSetup()
        assertEquals(AppMode.DASHBOARD, shell.mode)
        assertEquals(DashboardCategory.VEHICLES, shell.category)
        assertFalse(shell.takeCompanionHint())
        assertEquals(VehiclesPage.LIST, VehiclesState().page)
    }
}

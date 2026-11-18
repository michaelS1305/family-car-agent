package il.fca.companion

import android.app.Application
import android.app.NotificationManager
import android.content.ActivityNotFoundException
import android.content.Intent
import android.provider.Settings
import il.fca.companion.ui.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35, 36], application = Application::class)
class SettingsCapabilitiesTest {
    @Test fun locationRequiresEveryReturnPrerequisite() {
        for (fine in listOf(false, true)) for (background in listOf(false, true))
            for (enabled in listOf(false, true)) assertEquals(
                if (fine && background && enabled) CapabilityStatus.READY else CapabilityStatus.MISSING,
                locationStatus(fine, background, enabled))
        // Approximate-only access has fine=false and cannot pass.
    }

    @Test fun notificationsRequirePermissionAppAndChannel() {
        assertEquals(CapabilityStatus.READY, notificationStatus(true, true, NotificationManager.IMPORTANCE_LOW))
        assertEquals(CapabilityStatus.MISSING, notificationStatus(false, true, NotificationManager.IMPORTANCE_LOW))
        assertEquals(CapabilityStatus.MISSING, notificationStatus(true, false, NotificationManager.IMPORTANCE_LOW))
        assertEquals(CapabilityStatus.MISSING, notificationStatus(true, true, NotificationManager.IMPORTANCE_NONE))
        // Before first authenticated entry the channel need not exist yet.
        // This selector reports OS permission, not FCM registration/readiness.
        assertEquals(CapabilityStatus.READY, notificationStatus(true, true, null))
        assertEquals(CapabilityStatus.MISSING, notificationStatus(false, true, null))
        assertEquals(CapabilityStatus.MISSING, notificationStatus(true, false, null))
        assertEquals(CapabilityStatus.MISSING, notificationStatus(false, false, null))
    }

    @Test fun settingsDestinationsAndUnavailableFallback() {
        val pkg = "il.fca.companion.dev"
        val primary = notificationSettingsIntent(pkg)
        assertEquals(Settings.ACTION_APP_NOTIFICATION_SETTINGS, primary.action)
        assertEquals(pkg, primary.getStringExtra(Settings.EXTRA_APP_PACKAGE))
        assertEquals(Settings.ACTION_LOCATION_SOURCE_SETTINGS, locationSettingsIntent(pkg, false).action)
        val details = appDetailsIntent(pkg)
        assertEquals("package:$pkg", details.data.toString())
        assertEquals(details.action, locationSettingsIntent(pkg, true).action)
        assertEquals(details.action, locationSettingsIntent(pkg, null).action)
        val calls = mutableListOf<Intent>()
        assertTrue(launchSettings(primary, details) {
            calls += it
            if (it === primary) throw ActivityNotFoundException()
        })
        assertEquals(listOf(primary, details), calls)
        assertFalse(launchSettings(primary, details) { throw ActivityNotFoundException() })
    }

    @Test fun companionHintIsShortcutOnlyConsumedOnceAndClearedOnNavigation() {
        val state = AppShellState()
        state.select(AppMode.DASHBOARD)
        state.openCategory(DashboardCategory.VEHICLES)
        assertFalse(state.takeCompanionHint())
        state.openCategory(DashboardCategory.SETTINGS)
        state.openCompanionVehicles()
        assertEquals(DashboardCategory.VEHICLES, state.category)
        assertTrue(state.takeCompanionHint())
        assertFalse(state.takeCompanionHint())
        state.openCategory(DashboardCategory.SETTINGS)
        state.openCompanionVehicles()
        state.back()
        assertFalse(state.takeCompanionHint())
        assertNull(state.category)
        assertFalse(AppShellState().takeCompanionHint())
        assertTrue(COMPANION_VEHICLES_HINT.contains("חיבור וזיהוי אוטומטי"))
    }
}

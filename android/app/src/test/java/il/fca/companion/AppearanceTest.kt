package il.fca.companion

import android.app.Application
import androidx.compose.ui.graphics.luminance
import android.content.Context
import il.fca.companion.ui.*
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class AppearanceTest {
    private val context get() = RuntimeEnvironment.getApplication()
    @Before fun clear() { context.getSharedPreferences("fca_appearance", Context.MODE_PRIVATE).edit().clear().commit() }
    @Test fun defaultIsSystemAndTracksSystemChanges() {
        val mode = AppearanceStore(context).read()
        assertEquals(Appearance.SYSTEM, mode)
        assertFalse(mode.dark(false)); assertTrue(mode.dark(true))
    }
    @Test fun explicitOverridesPersistAcrossStoreRecreation() {
        for (mode in Appearance.entries) {
            AppearanceStore(context).select(mode)
            assertEquals(mode, AppearanceStore(context).read())
        }
        assertFalse(Appearance.LIGHT.dark(true))
        assertTrue(Appearance.DARK.dark(false))
    }
    @Test fun preferencesAreIndependentOfAuthentication() {
        AppearanceStore(context).select(Appearance.DARK)
        context.getSharedPreferences("auth", Context.MODE_PRIVATE).edit().clear().commit()
        assertEquals(Appearance.DARK, AppearanceStore(context).read())
    }
    @Test fun invalidStoredValueSafelyDefaultsToSystem() {
        context.getSharedPreferences("fca_appearance", Context.MODE_PRIVATE).edit().putString("mode", "invalid").commit()
        assertEquals(Appearance.SYSTEM, AppearanceStore(context).read())
    }
    @Test fun schemesAndSemanticTokensAgree() {
        assertEquals(FcaDarkColors.background, fcaColorScheme(true).background)
        assertEquals(FcaLightColors.text, fcaColorScheme(false).onSurface)
        assertNotEquals(fcaColorScheme(true).background, fcaColorScheme(false).background)
    }

    @Test fun darkSemanticTextMeetsAAOnItsActualSurfaces() {
        fun contrast(a: androidx.compose.ui.graphics.Color, b: androidx.compose.ui.graphics.Color): Double {
            val x = a.luminance().toDouble(); val y = b.luminance().toDouble()
            return (maxOf(x, y) + .05) / (minOf(x, y) + .05)
        }
        val c = FcaDarkColors
        val pairs = listOf(c.text to c.background, c.text to c.surface,
            c.secondaryText to c.surface, c.onDisabled to c.disabled,
            c.onSelected to c.selected, c.text to c.chatIncoming, c.text to c.chatOutgoing,
            c.calendarOutside to c.surface, c.success to c.surface, c.warning to c.surface,
            c.danger to c.color(FcaColorRole.DANGER_SURFACE))
        pairs.forEachIndexed { index, (foreground, background) ->
            assertTrue("Dark text pair $index must meet 4.5:1", contrast(foreground, background) >= 4.5)
        }
    }
    @Test fun capturedDrawingPalettePreservesLightAndUsesSharedDarkRoles() {
        val legacy = androidx.compose.ui.graphics.Color(0xFF637B97)
        for (role in FcaColorRole.entries) {
            assertEquals(legacy, FcaPalette(false, FcaLightColors).resolve(legacy, role))
            assertEquals(FcaDarkColors.color(role), FcaPalette(true, FcaDarkColors).resolve(legacy, role))
        }
        val scheme = fcaColorScheme(true)
        assertEquals(FcaDarkColors.surface, scheme.surfaceContainer)
        assertEquals(FcaDarkColors.text, scheme.onPrimaryContainer)
        assertEquals(FcaDarkColors.disabled, scheme.surfaceContainerHigh)
    }
}

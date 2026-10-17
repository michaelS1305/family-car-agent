package il.fca.companion

import android.app.Application
import android.os.Looper
import android.view.View
import android.view.ViewGroup
import androidx.activity.ComponentActivity
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.platform.ViewRootForTest
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.LayoutDirection
import il.fca.companion.ui.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@OptIn(ExperimentalComposeUiApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class, qualifiers = "w360dp-h640dp-mdpi")
class SettingsScreenTest {
    @Test fun approvedAssetsIncludingConvertedThemeInflate() {
        val context = RuntimeEnvironment.getApplication()
        for (resource in listOf(R.drawable.theme_icon, R.drawable.settings_icon,
            R.drawable.fca_header_wordmark, R.drawable.user_icon, R.drawable.family_icon,
            R.drawable.envelope_icon, R.drawable.location_icon, R.drawable.bell_icon,
            R.drawable.single_car_icon, R.drawable.about_icon, R.drawable.privacy_icon,
            R.drawable.info_icon, R.drawable.support_icon, R.drawable.chat_suppory_icon,
            R.drawable.logout_icon, R.drawable.delete_account_icon, R.drawable.trash_icon,
            R.drawable.clock_icon, R.drawable.ic_chevron_back, R.drawable.ic_chevron_right)) {
            assertTrue(context.getDrawable(resource) is android.graphics.drawable.VectorDrawable)
        }
    }

    private fun render(content: @Composable () -> Unit, check: (List<SemanticsNode>) -> Unit) {
        val controller = Robolectric.buildActivity(ComponentActivity::class.java).setup()
        val view = ComposeView(controller.get()).apply {
            setContent { MaterialTheme {
                CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) { content() }
            } }
        }
        try {
            controller.get().setContentView(view)
            shadowOf(Looper.getMainLooper()).idle()
            view.measure(View.MeasureSpec.makeMeasureSpec(360, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(640, View.MeasureSpec.EXACTLY))
            view.layout(0, 0, 360, 640)
            fun root(candidate: View): ViewRootForTest? {
                if (candidate is ViewRootForTest) return candidate
                if (candidate is ViewGroup) for (i in 0 until candidate.childCount)
                    root(candidate.getChildAt(i))?.let { return it }
                return null
            }
            check(checkNotNull(root(view)).semanticsOwner.getAllSemanticsNodes(false))
        } finally {
            view.disposeComposition()
            controller.pause().stop().destroy()
        }
    }

    private fun List<SemanticsNode>.withText(text: String) = single { node ->
        node.config.getOrNull(SemanticsProperties.Text)?.any { it.text == text } == true
    }
    private fun List<SemanticsNode>.activeClicks() = filter {
        it.config.contains(SemanticsActions.OnClick) && !it.config.contains(SemanticsProperties.Disabled)
    }
    private fun SemanticsNode.isDisabled(): Boolean =
        config.contains(SemanticsProperties.Disabled) || parent?.isDisabled() == true

    @Test fun onlyApprovedShortcutsBackAndTwoLocalSheetsAreInteractive() {
        var backed = false
        val state = AppShellState().apply {
            select(AppMode.DASHBOARD)
            openCategory(DashboardCategory.SETTINGS)
        }
        render({ SettingsScreen("דנה לוי",
            openFamily = { state.openCategory(DashboardCategory.FAMILY) },
            openCompanion = state::openCompanionVehicles) { backed = true } }) { nodes ->
            assertEquals(7, nodes.activeClicks().size)
            nodes.withText("דנה לוי")
            nodes.withText(BuildConfig.VERSION_NAME)
            assertTrue(nodes.any { it.config.contains(SemanticsActions.ScrollBy) })
            for (text in listOf("תנאי שימוש", "מדיניות פרטיות", "התנתקות")) {
                assertTrue(text, nodes.withText(text).isDisabled())
            }
            val familyLabel = nodes.withText("המשפחה שלי")
            assertFalse(familyLabel.isDisabled())
            val family = generateSequence(familyLabel) { it.parent }
                .first { it.config.contains(SemanticsActions.OnClick) }
            checkNotNull(family.config[SemanticsActions.OnClick].action).invoke()
            assertEquals(DashboardCategory.FAMILY, state.category)
            state.back()
            assertNull(state.category)
            assertEquals(AppMode.DASHBOARD, state.mode)
            state.openCategory(DashboardCategory.SETTINGS)
            val companion = generateSequence(nodes.withText("Android Companion")) { it.parent }
                .first { it.config.contains(SemanticsActions.OnClick) }
            checkNotNull(companion.config[SemanticsActions.OnClick].action).invoke()
            assertEquals(DashboardCategory.VEHICLES, state.category)
            assertTrue(state.takeCompanionHint())
            assertFalse(state.takeCompanionHint())
            val backLabel = nodes.single {
                it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains("חזרה לדשבורד") == true
            }
            val back = generateSequence(backLabel) { it.parent }.first { it.config.contains(SemanticsActions.OnClick) }
            assertTrue(back.boundsInRoot.left < 32f)
            checkNotNull(back.config[SemanticsActions.OnClick].action).invoke()
            assertTrue(backed)
        }
    }

    @Test fun missingNameUsesFallbackWithoutFabricatingAccountData() {
        render({ SettingsScreen("  ", openFamily = {}, openCompanion = {}) {} }) { nodes ->
            assertTrue(3 <= nodes.count { node -> node.config.getOrNull(SemanticsProperties.Text)
                ?.any { it.text == "טרם הוגדר" } == true })
            assertFalse(nodes.any { node -> node.config.getOrNull(SemanticsProperties.Text)
                ?.any { it.text.contains("@") || it.text == "מאושר" || it.text == "מוכן" } == true })
        }
    }

    @Test fun allSheetsOnlyExposeDismissAndDeletionIsDisabled() {
        for (sheet in SettingsSheet.entries) {
            var dismissed = false
            render({ SettingsSheetContent(sheet) { dismissed = true } }) { nodes ->
                val clicks = nodes.activeClicks()
                assertEquals(sheet.name, 1, clicks.size)
                if (sheet == SettingsSheet.DELETE_ACCOUNT) {
                    assertTrue(nodes.withText("המשך למחיקה").isDisabled())
                }
                checkNotNull(clicks.single().config[SemanticsActions.OnClick].action).invoke()
                assertTrue(dismissed)
            }
        }
    }

    @Test fun settingsReturnsToDashboardUsingExistingState() {
        val state = AppShellState()
        state.select(AppMode.DASHBOARD)
        state.openCategory(DashboardCategory.SETTINGS)
        assertEquals(DashboardCategory.SETTINGS, state.category)
        state.back()
        assertNull(state.category)
        assertEquals(AppMode.DASHBOARD, state.mode)
    }
}

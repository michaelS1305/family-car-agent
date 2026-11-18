package il.fca.companion

import android.app.Application
import android.os.Looper
import android.view.View
import android.view.ViewGroup
import androidx.activity.ComponentActivity
import androidx.compose.material3.MaterialTheme
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
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class, qualifiers = "w360dp-h640dp-mdpi")
class DashboardTest {
    @OptIn(ExperimentalComposeUiApi::class)
    @Test fun renderedDashboardHasOnlyFiveCategoryActionsAndLogoutAndNoScrolling() {
        val controller = Robolectric.buildActivity(ComponentActivity::class.java).setup()
        val clicked = mutableListOf<DashboardCategory>()
        var signedOut = false
        val view = ComposeView(controller.get()).apply {
            setContent {
                MaterialTheme {
                    CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
                        DashboardScreen("דנה לוי", clicked::add, { signedOut = true }, false, null)
                    }
                }
            }
        }
        try {
            controller.get().setContentView(view)
            shadowOf(Looper.getMainLooper()).idle()
            view.measure(View.MeasureSpec.makeMeasureSpec(360, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(560, View.MeasureSpec.EXACTLY))
            view.layout(0, 0, 360, 560)
            fun findRoot(candidate: View): ViewRootForTest? {
                if (candidate is ViewRootForTest) return candidate
                if (candidate is ViewGroup) for (i in 0 until candidate.childCount) {
                    findRoot(candidate.getChildAt(i))?.let { return it }
                }
                return null
            }
            val nodes = checkNotNull(findRoot(view)).semanticsOwner.getAllSemanticsNodes(false)
            val actions = nodes.filter { it.config.contains(SemanticsActions.OnClick) }
            assertEquals(6, actions.size) // No action on a sector, label or center hub.
            for (category in DashboardCategory.entries) {
                val node = actions.single {
                    it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains(category.label) == true
                }
                assertEquals(Role.Button, node.config[SemanticsProperties.Role])
                assertTrue(node.boundsInRoot.width >= 48f)
                assertTrue(node.boundsInRoot.height >= 48f)
                assertTrue(checkNotNull(node.config[SemanticsActions.OnClick].action).invoke())
            }
            assertEquals(DashboardCategory.entries.toList(), clicked)
            assertFalse(nodes.any { node -> node.config.getOrNull(SemanticsProperties.Text)
                ?.any { text -> DashboardCategory.entries.any { it.label == text.text } } == true })
            assertTrue(nodes.any { node -> node.config.getOrNull(SemanticsProperties.Text)
                ?.any { it.text == "היי, דנה" } == true })
            assertFalse(nodes.any { it.config.contains(SemanticsActions.ScrollBy) ||
                it.config.contains(SemanticsProperties.VerticalScrollAxisRange) })
            val logout = actions.single { it.config.getOrNull(SemanticsProperties.ContentDescription) == null }
            checkNotNull(logout.config[SemanticsActions.OnClick].action).invoke()
            assertTrue(signedOut)
            for ((width, height) in listOf(320 to 460, 412 to 720)) {
                view.measure(View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY),
                    View.MeasureSpec.makeMeasureSpec(height, View.MeasureSpec.EXACTLY))
                view.layout(0, 0, width, height)
                shadowOf(Looper.getMainLooper()).idle()
                val buttons = checkNotNull(findRoot(view)).semanticsOwner.getAllSemanticsNodes(false)
                    .filter { it.config.contains(SemanticsActions.OnClick) }
                assertEquals(6, buttons.size)
                buttons.forEach { node ->
                    val bounds = node.boundsInRoot
                    assertTrue("$width x $height: $bounds", bounds.left >= 0f && bounds.top >= 0f &&
                        bounds.right <= width && bounds.bottom <= height)
                    assertTrue(bounds.width >= 48f && bounds.height >= 48f)
                }
                buttons.forEachIndexed { index, node ->
                    buttons.drop(index + 1).forEach { other ->
                        assertFalse("Touch targets overlap", node.boundsInRoot.overlaps(other.boundsInRoot))
                    }
                }
            }
        } finally {
            view.disposeComposition()
            controller.pause().stop().destroy()
        }
    }
    @Test fun eachCategoryOpensItsOwnPlaceholderWithinDashboard() {
        for (category in DashboardCategory.entries) {
            val shell = AppShellState()
            shell.select(AppMode.DASHBOARD)
            shell.openCategory(category)
            assertEquals(category, shell.category)
            assertEquals(AppMode.DASHBOARD, shell.mode)
            shell.back()
            assertNull(shell.category)
            assertEquals(AppMode.DASHBOARD, shell.mode)
            shell.back()
            assertEquals(AppMode.CHAT, shell.mode)
        }
    }

    @Test fun switchingModesDropsOnlyTheCategoryDestination() {
        val shell = AppShellState()
        shell.openCategory(DashboardCategory.FAMILY)
        assertNull(shell.category)
        shell.select(AppMode.DASHBOARD)
        shell.openCategory(DashboardCategory.HISTORY)
        shell.select(AppMode.CHAT)
        assertNull(shell.category)
        shell.select(AppMode.DASHBOARD)
        assertNull(shell.category)
    }

    @Test fun greetingUsesSuppliedNameWithoutInventingOne() {
        assertEquals("היי, ז׳אנה", dashboardGreeting(" ז׳אנה כהן "))
        assertEquals("היי, דנה", dashboardGreeting("דנה\u00a0לוי"))
        assertEquals("היי", dashboardGreeting(""))
    }

    @Test fun categoriesMatchClockwiseReferenceAndExactResources() {
        assertEquals(listOf("משפחה", "רכבים", "הגדרות", "היסטוריה", "מרכז הזמנות"),
            DashboardCategory.entries.map { it.label })
        assertEquals(listOf(R.drawable.family_icon, R.drawable.vehicles_icon, R.drawable.settings_icon,
            R.drawable.history_icon, R.drawable.booking_center_icon), DashboardCategory.entries.map { it.asset })
        assertEquals(.5f, DashboardCategory.FAMILY.anchorX)
        assertTrue(DashboardCategory.VEHICLES.anchorX > .5f)
        assertTrue(DashboardCategory.SETTINGS.anchorY > .5f)
        assertTrue(DashboardCategory.HISTORY.anchorX < .5f)
        assertTrue(DashboardCategory.BOOKING_CENTER.anchorY < .5f)
    }
}

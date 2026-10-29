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
import kotlinx.coroutines.*
import androidx.compose.runtime.BroadcastFrameClock
import androidx.compose.runtime.Recomposer
import androidx.compose.runtime.snapshots.Snapshot
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import org.json.JSONObject

@OptIn(ExperimentalComposeUiApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class, qualifiers = "w360dp-h640dp-mdpi")
class SettingsScreenTest {
    @Test fun firstVehicleDialogRendersExactCopyAndRoutesBothControls() {
        for (dark in listOf(false, true)) {
            var dismissed = 0
            var setup = 0
            render({ CompositionLocalProvider(LocalFcaDark provides dark,
                LocalFcaColors provides if (dark) FcaDarkColors else FcaLightColors) {
                FirstVehicleSetupDialog({ dismissed++ }, { setup++ })
            } }) {
                val nodes = mutableListOf<SemanticsNode>()
                fun collect(view: View) {
                    if (view is ViewRootForTest) nodes += view.semanticsOwner.getAllSemanticsNodes(false)
                    if (view is ViewGroup) repeat(view.childCount) { collect(view.getChildAt(it)) }
                }
                android.view.inspector.WindowInspector.getGlobalWindowViews().filter { it.isShown }.forEach(::collect)
                nodes.withText("שנתחבר?")
                nodes.withText("זה לוקח דקה והסוכן מחובר לרכב ומעדכן אוטומטית")
                val cta = generateSequence(nodes.withText("להגדרה")) { it.parent }
                    .first { it.config.contains(SemanticsActions.OnClick) }
                cta.config[SemanticsActions.OnClick].action!!.invoke()
                assertEquals(1, setup); assertEquals(0, dismissed)
                val back = nodes.first { it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains("חזרה") == true }
                generateSequence(back) { it.parent }.first { it.config.contains(SemanticsActions.OnClick) }
                    .config[SemanticsActions.OnClick].action!!.invoke()
                assertEquals(1, dismissed)
            }
        }
    }
    @Test fun actualAuthenticatedEmailAppearsAsAccountValue() = runBlocking {
        val model = AccountSettingsModel(object : AccountSettingsGateway {
            override suspend fun email(owner: String) = "actual@example.test"
            override suspend fun request(owner: String, method: String, preview: Boolean): JSONObject =
                error("No deletion request without confirmation")
        }, { AccountIdentity("A", 1) }, this)
        model.loadEmail(); yield()
        render({ SettingsScreen("דנה", logout = {}, openFamily = {}, openCompanion = {}, account = model) {} }) {
            it.withText("actual@example.test")
        }
    }
    @Test fun logoutUsesProvidedActionAndBusyDisablesRepeatedTaps() {
        for (busy in listOf(false, true)) {
            var calls = 0
            render({ SettingsScreen("", openFamily = {}, openCompanion = {},
                logout = { calls++ }, logoutBusy = busy) {} }) { nodes ->
                val label = nodes.withText("התנתקות")
                assertEquals(busy, label.isDisabled())
                val row = generateSequence(label) { it.parent }
                    .first { it.config.contains(SemanticsActions.OnClick) }
                repeat(2) { row.config[SemanticsActions.OnClick].action?.invoke() }
                assertEquals(if (busy) 0 else 2, calls)
            }
        }
    }

    @Test fun deletionClickDisplaysDialogAfterInitiallyInactiveIdentityWithoutPosting() {
        val calls = mutableListOf<String>()
        val scope = kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.SupervisorJob() + kotlinx.coroutines.Dispatchers.Unconfined)
        val model = AccountSettingsModel(object : AccountSettingsGateway {
            override suspend fun email(owner: String): String? = null
            override suspend fun request(owner: String, method: String, preview: Boolean): JSONObject {
                calls += "$method:$preview"
                check(method == "GET")
                return if (preview) JSONObject().put("consequence", "personal")
                    else JSONObject().put("status", "not_requested")
            }
        }, { AccountIdentity("A", 1) }, scope)
        try {
            render({ FcaTheme {
                SettingsScreen("", openFamily = {}, openCompanion = {}, account = model, logout = {}) {}
                AccountDeletionDialog(model, {}, false, null)
            } }) { nodes ->
                val button = generateSequence(nodes.withText("מחיקת חשבון")) { it.parent }
                    .first { it.config.contains(SemanticsActions.OnClick) }
                button.config[SemanticsActions.OnClick].action!!.invoke()
                // State changes schedule a Compose frame, not just a message-queue task.
                advanceComposition()
                assertTrue(model.state.dialog)
                assertEquals(listOf("GET:false", "GET:true"), calls)
                val windows = android.view.inspector.WindowInspector.getGlobalWindowViews()
                fun containsConfirmation(view: View): Boolean {
                    if (view is ViewRootForTest && view.semanticsOwner.getAllSemanticsNodes(false).any {
                        it.config.getOrNull(SemanticsProperties.Text)?.any { text ->
                            text.text == "אני מאשר/ת מחיקה לצמיתות"
                        } == true
                    }) return true
                    return view is ViewGroup && (0 until view.childCount).any { containsConfirmation(view.getChildAt(it)) }
                }
                assertTrue("Confirmation must be present in a visible attached window (windows=${windows.size})",
                    windows.any { it.isShown && containsConfirmation(it) })
            }
        } finally { scope.coroutineContext[kotlinx.coroutines.Job]?.cancel() }
    }

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

    @Test fun appearanceSelectionPersistsAndPropagatesThroughTheme() {
        val store = AppearanceStore(RuntimeEnvironment.getApplication())
        store.select(Appearance.LIGHT)
        try {
            render({ FcaTheme { SettingsScreen("", openFamily = {}, openCompanion = {}, logout = {}) {} } }) { nodes ->
                val dark = nodes.withText("כהה")
                assertFalse(dark.isDisabled())
                val action = generateSequence(dark) { it.parent }.first { it.config.contains(SemanticsActions.OnClick) }
                action.config[SemanticsActions.OnClick].action!!.invoke()
                assertEquals(Appearance.DARK, store.read())
            }
            var propagated = false
            render({ FcaTheme {
                propagated = LocalFcaDark.current && LocalAppearance.current.selected == Appearance.DARK &&
                    MaterialTheme.colorScheme.background == FcaDarkColors.background
                androidx.compose.material3.Text("theme probe")
            } }) { assertTrue(propagated) }
        } finally { store.select(Appearance.SYSTEM) }
    }


    @Test fun deletionConfirmationAlsoRemainsVisibleInDarkMode() {
        val store = AppearanceStore(RuntimeEnvironment.getApplication())
        store.select(Appearance.DARK)
        try { deletionClickDisplaysDialogAfterInitiallyInactiveIdentityWithoutPosting() }
        finally { store.select(Appearance.SYSTEM) }
    }

    @Test fun liveSystemChangesAndOverridesPropagateWithoutLosingRememberedState() {
        val store = AppearanceStore(RuntimeEnvironment.getApplication())
        store.select(Appearance.SYSTEM)
        val configuration = androidx.compose.runtime.mutableStateOf(android.content.res.Configuration().apply {
            uiMode = android.content.res.Configuration.UI_MODE_NIGHT_NO
        })
        var dark = true
        var text = FcaLightColors.text
        var remembered: Any? = null
        var control: AppearanceControl? = null
        try {
            render({ CompositionLocalProvider(androidx.compose.ui.platform.LocalConfiguration provides configuration.value) {
                FcaTheme {
                    dark = LocalFcaDark.current
                    text = fcaColor(androidx.compose.ui.graphics.Color.Black, FcaColorRole.TEXT)
                    remembered = androidx.compose.runtime.remember { Any() }
                    control = LocalAppearance.current
                    UserAvatar("בדיקה", androidx.compose.ui.unit.Dp(26f))
                }
            } }) {
                assertFalse(dark)
                val original = remembered
                configuration.value = android.content.res.Configuration(configuration.value).apply {
                    uiMode = android.content.res.Configuration.UI_MODE_NIGHT_YES
                }
                advanceComposition()
                assertTrue(dark); assertEquals(FcaDarkColors.text, text); assertSame(original, remembered)
                control!!.select(Appearance.LIGHT); advanceComposition()
                assertFalse(dark); assertSame(original, remembered)
                control!!.select(Appearance.DARK); advanceComposition()
                configuration.value = android.content.res.Configuration(configuration.value).apply {
                    uiMode = android.content.res.Configuration.UI_MODE_NIGHT_NO
                }
                advanceComposition()
                assertTrue(dark); assertSame(original, remembered)
                control!!.select(Appearance.SYSTEM); advanceComposition()
                assertFalse(dark); assertSame(original, remembered)
            }
        } finally { store.select(Appearance.SYSTEM) }
    }

    private var advanceComposition: () -> Unit = {}

    private fun render(content: @Composable () -> Unit, check: (List<SemanticsNode>) -> Unit) {
        val controller = Robolectric.buildActivity(ComponentActivity::class.java).setup().visible()
        val clock = BroadcastFrameClock()
        val scope = CoroutineScope(Dispatchers.Main.immediate + clock + SupervisorJob())
        val recomposer = Recomposer(scope.coroutineContext)
        scope.launch(start = CoroutineStart.UNDISPATCHED) { recomposer.runRecomposeAndApplyChanges() }
        var frame = 0L
        advanceComposition = {
            repeat(3) {
                Snapshot.sendApplyNotifications()
                shadowOf(Looper.getMainLooper()).idle()
                clock.sendFrame(++frame * 16_000_000L)
                shadowOf(Looper.getMainLooper()).idle()
            }
        }
        val view = ComposeView(controller.get()).apply {
            setParentCompositionContext(recomposer)
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
            recomposer.close(); scope.cancel(); advanceComposition = {}
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
        render({ SettingsScreen("דנה לוי", logout = {},
            openFamily = { state.openCategory(DashboardCategory.FAMILY) },
            openCompanion = state::openCompanionVehicles) { backed = true } }) { nodes ->
            for (label in listOf("מערכת", "בהיר", "כהה")) {
                assertFalse(nodes.withText(label).isDisabled())
                assertTrue(generateSequence(nodes.withText(label)) { it.parent }
                    .any { it.config.contains(SemanticsActions.OnClick) })
            }
            nodes.withText("דנה לוי")
            nodes.withText(BuildConfig.VERSION_NAME)
            assertTrue(nodes.any { it.config.contains(SemanticsActions.ScrollBy) })
            for (text in listOf("תנאי שימוש", "מדיניות פרטיות")) {
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
        render({ SettingsScreen("  ", logout = {}, openFamily = {}, openCompanion = {}) {} }) { nodes ->
            // Only account name/email are placeholders; permission rows now reflect real capabilities.
            assertEquals(2, nodes.count { node -> node.config.getOrNull(SemanticsProperties.Text)
                ?.any { it.text == "טרם הוגדר" } == true })
            assertFalse(nodes.any { node -> node.config.getOrNull(SemanticsProperties.Text)
                ?.any { it.text.contains("@") } == true })
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

package il.fca.companion.ui

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.res.Configuration
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat
import androidx.core.content.edit

internal enum class Appearance(val label: String) { SYSTEM("מערכת"), LIGHT("בהיר"), DARK("כהה");
    fun dark(systemDark: Boolean) = this == DARK || (this == SYSTEM && systemDark)
}

/** Device preference only. Deliberately separate from authentication and Companion storage. */
internal class AppearanceStore(context: Context) {
    private val preferences = context.applicationContext.getSharedPreferences("fca_appearance", Context.MODE_PRIVATE)
    fun read(): Appearance = runCatching { Appearance.valueOf(preferences.getString("mode", null) ?: "SYSTEM") }.getOrDefault(Appearance.SYSTEM)
    fun select(mode: Appearance) { preferences.edit { putString("mode", mode.name) } }
    fun observe(changed: () -> Unit): () -> Unit {
        val listener = android.content.SharedPreferences.OnSharedPreferenceChangeListener { _, key -> if (key == "mode") changed() }
        preferences.registerOnSharedPreferenceChangeListener(listener)
        return { preferences.unregisterOnSharedPreferenceChangeListener(listener) }
    }
}

internal data class FcaColors(
    val background: Color, val surface: Color, val text: Color, val secondaryText: Color,
    val border: Color, val selected: Color, val onSelected: Color,
    val disabled: Color, val onDisabled: Color, val success: Color, val warning: Color, val danger: Color,
    val chatOutgoing: Color, val chatIncoming: Color, val calendarToday: Color, val calendarOutside: Color
)
internal val FcaLightColors = FcaColors(
    Color(0xFFF6F7F7), Color.White, Color(0xFF243341), Color(0xFF53677D),
    Color(0xFFCCD4DC), Color(0xFF245B9B), Color.White, Color(0xFFE4E9EC), Color(0xFF596672),
    Color(0xFF176B45), Color(0xFF805000), Color(0xFFB3261E),
    Color(0xFFDCEBFA), Color(0xFFE9EEF0), Color(0xFF245B9B), Color(0xFF697583))
internal val FcaDarkColors = FcaColors(
    Color(0xFF121A22), Color(0xFF1D2833), Color(0xFFEDF2F7), Color(0xFFBAC8D5),
    Color(0xFF596B7C), Color(0xFFA9CDF8), Color(0xFF102D4F), Color(0xFF303D49), Color(0xFFADB9C5),
    Color(0xFF8BD8AD), Color(0xFFFFD18A), Color(0xFFFFB4AB),
    Color(0xFF244663), Color(0xFF2D3945), Color(0xFFA9CDF8), Color(0xFF9DABB9))
internal fun fcaColorScheme(dark: Boolean): ColorScheme {
    val c = if (dark) FcaDarkColors else FcaLightColors
    val base = if (dark) darkColorScheme() else lightColorScheme()
    val scheme = base.copy(primary = c.selected, onPrimary = c.onSelected,
        secondary = c.secondaryText, onSecondary = c.background,
        background = c.background, onBackground = c.text, surface = c.surface, onSurface = c.text,
        surfaceVariant = c.disabled, onSurfaceVariant = c.secondaryText,
        outline = c.border, outlineVariant = c.border, error = c.danger,
        surfaceTint = Color.Transparent)
    // Preserve the existing light scheme; remove Material's unrelated purple containers in dark.
    return if (!dark) scheme else scheme.copy(
        primaryContainer = c.chatOutgoing, onPrimaryContainer = c.text,
        secondaryContainer = c.disabled, onSecondaryContainer = c.text,
        tertiary = c.selected, onTertiary = c.onSelected,
        tertiaryContainer = c.disabled, onTertiaryContainer = c.text,
        errorContainer = c.color(FcaColorRole.DANGER_SURFACE), onErrorContainer = c.danger,
        onError = c.background, inverseSurface = c.text, inverseOnSurface = c.background,
        inversePrimary = FcaLightColors.selected,
        surfaceDim = c.background, surfaceBright = c.disabled,
        surfaceContainerLowest = c.background, surfaceContainerLow = c.surface,
        surfaceContainer = c.surface, surfaceContainerHigh = c.disabled,
        surfaceContainerHighest = c.chatIncoming)
}
internal val LocalFcaColors = staticCompositionLocalOf { FcaLightColors }
internal val LocalFcaDark = staticCompositionLocalOf { false }
internal data class AppearanceControl(val selected: Appearance, val select: (Appearance) -> Unit)
internal val LocalAppearance = staticCompositionLocalOf { AppearanceControl(Appearance.SYSTEM) {} }

@Composable
internal fun FcaTheme(content: @Composable () -> Unit) {
    val context = LocalContext.current
    val store = remember(context.applicationContext) { AppearanceStore(context) }
    var mode by remember(store) { mutableStateOf(store.read()) }
    DisposableEffect(store) {
        val stop = store.observe { mode = store.read() }
        mode = store.read()
        onDispose { stop() }
    }
    val dark = mode.dark(isSystemInDarkTheme())
    val view = LocalView.current
    SideEffect {
        var current: Context = context
        while (current is ContextWrapper && current !is Activity) current = current.baseContext
        (current as? Activity)?.let {
            WindowCompat.getInsetsController(it.window, view).apply {
                isAppearanceLightStatusBars = !dark
                isAppearanceLightNavigationBars = !dark
            }
            @Suppress("DEPRECATION")
            it.window.apply {
                statusBarColor = if (dark) 0xFF121A22.toInt() else 0xFFF6F7F7.toInt()
                navigationBarColor = statusBarColor
            }
        }
    }
    CompositionLocalProvider(LocalFcaDark provides dark,
        LocalFcaColors provides if (dark) FcaDarkColors else FcaLightColors,
        LocalAppearance provides AppearanceControl(mode) { mode = it; store.select(it) }) {
        MaterialTheme(colorScheme = fcaColorScheme(dark), content = content)
    }
}

/** Must run before Activity super.onCreate for the separate platform-Views path. */
internal fun applyFcaPlatformTheme(activity: Activity) {
    val systemDark = activity.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK == Configuration.UI_MODE_NIGHT_YES
    activity.setTheme(if (AppearanceStore(activity).read().dark(systemDark))
        il.fca.companion.R.style.Theme_Fca_Companion_Dark else il.fca.companion.R.style.Theme_Fca_Companion_Light)
}

/** Roles shared across screens. Existing light shades remain unchanged during migration. */
internal enum class FcaColorRole { BACKGROUND, SURFACE, ELEVATED, TEXT, SECONDARY, BORDER, ACTION, ON_ACTION,
    DISABLED, SUCCESS, WARNING, DANGER, DANGER_SURFACE, CHAT_INCOMING, CHAT_OUTGOING, OUTSIDE_DATE }
internal fun FcaColors.color(role: FcaColorRole): Color = when (role) {
    FcaColorRole.BACKGROUND -> background
    FcaColorRole.SURFACE -> surface
    FcaColorRole.ELEVATED -> disabled
    FcaColorRole.TEXT -> text
    FcaColorRole.SECONDARY -> secondaryText
    FcaColorRole.BORDER -> border
    FcaColorRole.ACTION -> selected
    FcaColorRole.ON_ACTION -> onSelected
    FcaColorRole.DISABLED -> onDisabled
    FcaColorRole.SUCCESS -> success
    FcaColorRole.WARNING -> warning
    FcaColorRole.DANGER -> danger
    FcaColorRole.DANGER_SURFACE -> Color(0xFF44292E)
    FcaColorRole.CHAT_INCOMING -> chatIncoming
    FcaColorRole.CHAT_OUTGOING -> chatOutgoing
    FcaColorRole.OUTSIDE_DATE -> calendarOutside
}
@Composable
internal fun fcaColor(light: Color, role: FcaColorRole): Color =
    if (LocalFcaDark.current) LocalFcaColors.current.color(role) else light

/** Snapshot captured in composition; safe to use inside drawing callbacks. */
internal class FcaPalette(private val dark: Boolean, private val colors: FcaColors) {
    fun resolve(light: Color, role: FcaColorRole): Color = if (dark) colors.color(role) else light
}
@Composable internal fun fcaPalette(): FcaPalette = FcaPalette(LocalFcaDark.current, LocalFcaColors.current)

/** Only for monochrome control glyphs, never logos, photos or vehicle artwork. */
@Composable internal fun fcaControlIconFilter(): androidx.compose.ui.graphics.ColorFilter? =
    if (LocalFcaDark.current) androidx.compose.ui.graphics.ColorFilter.tint(LocalFcaColors.current.text) else null

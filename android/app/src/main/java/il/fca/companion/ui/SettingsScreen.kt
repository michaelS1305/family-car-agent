package il.fca.companion.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.AbsoluteAlignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.*
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.*
import il.fca.companion.BuildConfig
import il.fca.companion.R

private val SettingsBackground = Color(0xFFF6F7F7)
private val SettingsInk = Color(0xFF102D4F)
private val SettingsSecondary = Color(0xFF64748B)
private val SettingsBorder = Color(0xFFE4E9EF)
private val SettingsRed = Color(0xFFC92332)
private const val NotConfigured = "טרם הוגדר"
private const val Unavailable = "לא זמין בשלב זה"

// These retained sheets remain presentation-only.
internal enum class SettingsSheet { COMPANION, SUPPORT, DELETE_ACCOUNT }

@Composable
internal fun SettingsScreen(authenticatedName: String, openFamily: () -> Unit,
                           openCompanion: () -> Unit, back: () -> Unit) {
    val capabilities = rememberSettingsCapabilities()
    val context = androidx.compose.ui.platform.LocalContext.current
    var sheet by remember { mutableStateOf<SettingsSheet?>(null) }
    BackHandler(enabled = sheet == null, onBack = back)
    CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
        Column(Modifier.fillMaxSize().background(SettingsBackground).navigationBarsPadding(),
            horizontalAlignment = Alignment.CenterHorizontally) {
            SettingsHeader(back)
            Column(Modifier.widthIn(max = 620.dp).fillMaxWidth().weight(1f)
                .verticalScroll(rememberScrollState()).padding(horizontal = 18.dp)
                .padding(bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                // The approved category drawable includes the Hebrew title; do not duplicate it.
                Box(Modifier.fillMaxWidth().height(120.dp), contentAlignment = Alignment.Center) {
                    Image(painterResource(R.drawable.settings_icon), "הגדרות",
                        Modifier.requiredSize(240.dp).offset(y = (-16).dp), contentScale = ContentScale.Fit)
                }
                SettingsSection("חשבון") {
                    SettingsRow("שם", R.drawable.user_icon,
                        value = authenticatedName.takeIf { it.isNotBlank() } ?: NotConfigured)
                    SettingsDivider()
                    SettingsRow("המשפחה שלי", R.drawable.family_icon,
                        subtitle = "פתיחת ניהול המשפחה", chevron = true,
                        secondaryLabel = true, onClick = openFamily)
                    SettingsDivider()
                    SettingsRow("אימייל", R.drawable.envelope_icon, value = NotConfigured)
                }
                SettingsSection("תצוגה") { ThemePreview() }
                SettingsSection("הרשאות") {
                    SettingsRow("מיקום", R.drawable.location_icon, value = capabilities.location.text,
                        badge = true, chevron = true, secondaryLabel = true,
                        onClick = { openCapabilitySettings(context, location = true) })
                    SettingsDivider()
                    SettingsRow("התראות", R.drawable.bell_icon, value = capabilities.notifications.text,
                        badge = true, chevron = true, secondaryLabel = true,
                        onClick = { openCapabilitySettings(context, location = false) })
                    SettingsDivider()
                    SettingsRow("Android Companion", R.drawable.single_car_icon, value = NotConfigured,
                        badge = true, chevron = true, onClick = openCompanion)
                }
                SettingsSection("תנאי שימוש ופרטיות") {
                    SettingsRow("תנאי שימוש", R.drawable.about_icon, chevron = true, unavailable = true)
                    SettingsDivider()
                    SettingsRow("מדיניות פרטיות", R.drawable.privacy_icon, chevron = true, unavailable = true)
                }
                SettingsSection("אודות") {
                    SettingsRow("גרסת האפליקציה", R.drawable.info_icon, value = BuildConfig.VERSION_NAME)
                    SettingsDivider()
                    SettingsRow("צור קשר לתמיכה", R.drawable.support_icon, chevron = true,
                        onClick = { sheet = SettingsSheet.SUPPORT })
                }
                DangerRow("התנתקות", R.drawable.logout_icon)
                DangerRow("מחיקת חשבון", R.drawable.delete_account_icon) { sheet = SettingsSheet.DELETE_ACCOUNT }
            }
        }
        sheet?.let { SettingsPresentationSheet(it) { sheet = null } }
    }
}

@Composable
private fun SettingsHeader(back: () -> Unit) {
    Box(Modifier.fillMaxWidth().height(76.dp).padding(horizontal = 16.dp)) {
        Image(painterResource(R.drawable.fca_header_wordmark), "Family Car Agent",
            Modifier.align(Alignment.Center).fillMaxWidth(.63f).height(58.dp).graphicsLayer {
                compositingStrategy = CompositingStrategy.Offscreen
                blendMode = BlendMode.Multiply
            }, contentScale = ContentScale.Fit)
        // Explicit physical-left placement; keep the supplied back glyph pointing left in RTL.
        CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) {
            IconButton(back, Modifier.align(AbsoluteAlignment.CenterLeft).size(48.dp)
                .background(Color.White.copy(alpha = .85f), CircleShape)) {
                Image(painterResource(R.drawable.ic_chevron_back), "חזרה לדשבורד", Modifier.size(22.dp))
            }
        }
    }
}

@Composable
private fun SettingsSection(title: String, content: @Composable ColumnScope.() -> Unit) {
    Box(Modifier.fillMaxWidth()
        .border(1.dp, SettingsBorder, RoundedCornerShape(24.dp))
        .clip(RoundedCornerShape(24.dp))
        .semantics { isTraversalGroup = true }
        .pointerInput(Unit) {}, propagateMinConstraints = true) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 14.dp).padding(top = 14.dp, bottom = 6.dp)) {
            Text(title, Modifier.fillMaxWidth().padding(bottom = 10.dp), color = SettingsInk,
                fontSize = 18.sp, fontWeight = FontWeight.Bold)
            SettingsDivider()
            content()
        }
    }
}

@Composable
private fun SettingsDivider() = HorizontalDivider(color = SettingsBorder.copy(alpha = .7f))

@Composable
private fun SettingsAsset(resource: Int, size: Dp = 40.dp, tint: Color? = null,
                          artworkScale: Float = 1f, mirror: Boolean = false) {
    // Preserve complete approved artwork, including its intrinsic transparent canvas.
    Image(painterResource(resource), null, Modifier.size(size).graphicsLayer {
        scaleX = artworkScale * if (mirror) -1f else 1f
        scaleY = artworkScale
    }, contentScale = ContentScale.Fit,
        colorFilter = tint?.let { ColorFilter.tint(it) })
}

@Composable
private fun SettingsRow(
    label: String, icon: Int, value: String? = null, subtitle: String? = null,
    badge: Boolean = false, chevron: Boolean = false, unavailable: Boolean = false,
    secondaryLabel: Boolean = unavailable,
    onClick: (() -> Unit)? = null
) {
    val interaction = if (onClick != null) Modifier.clickable(role = Role.Button, onClick = onClick)
        else if (unavailable) Modifier.semantics(mergeDescendants = true) { disabled(); stateDescription = Unavailable }
        else Modifier
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).then(interaction)
        .heightIn(min = 64.dp).padding(vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        if (chevron) Image(painterResource(R.drawable.ic_chevron_right), null, Modifier.size(16.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Text(label, color = if (secondaryLabel) SettingsSecondary else SettingsInk, fontSize = 15.sp,
                fontWeight = FontWeight.Medium)
            subtitle?.let { Text(it, color = SettingsSecondary, fontSize = 12.sp) }
        }
        value?.let {
            Text(it, Modifier.weight(.85f).then(if (badge) Modifier
                .padding(horizontal = 8.dp, vertical = 5.dp)
                else Modifier), color = SettingsSecondary, fontSize = if (badge) 12.sp else 14.sp,
                textAlign = TextAlign.Center)
        }
        // Equal 40dp layout slots; compensate only for these assets' larger transparent margins.
        SettingsAsset(icon, artworkScale = when (icon) {
            R.drawable.user_icon -> 2f
            R.drawable.family_icon -> 1.8f
            else -> 1f
        }, mirror = icon == R.drawable.privacy_icon)
    }
}

@Composable
private fun ThemePreview() {
    Column(Modifier.fillMaxWidth().padding(vertical = 12.dp)
        .semantics(mergeDescendants = true) { disabled(); stateDescription = "בחירת תצוגה אינה זמינה בשלב זה" }) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(Modifier.weight(1f).background(Color(0xFFE9ECF1), RoundedCornerShape(16.dp)).padding(4.dp)) {
                listOf("מערכת", "בהיר", "כהה").forEach { label ->
                    Text(label, Modifier.weight(1f)
                        .background(if (label == "בהיר") Color.White else Color.Transparent, RoundedCornerShape(12.dp))
                        .padding(vertical = 10.dp), textAlign = TextAlign.Center, fontSize = 14.sp,
                        color = if (label == "בהיר") Color(0xFF326CB6) else SettingsSecondary)
                }
            }
            SettingsAsset(R.drawable.theme_icon)
        }
        Text("בחירת תצוגה אינה זמינה בשלב זה", Modifier.fillMaxWidth().padding(top = 6.dp),
            fontSize = 11.sp, color = SettingsSecondary, textAlign = TextAlign.Center)
    }
}

@Composable
private fun DangerRow(label: String, icon: Int, onClick: (() -> Unit)? = null) {
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp))
        .background(Color(0xFFFFEEEE)).border(1.dp, Color(0xFFF5D7DA), RoundedCornerShape(16.dp))
        .then(if (onClick != null) Modifier.clickable(role = Role.Button, onClick = onClick)
            else Modifier.semantics(mergeDescendants = true) { disabled(); stateDescription = Unavailable })
        .heightIn(min = 52.dp).padding(horizontal = 14.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Image(painterResource(R.drawable.ic_chevron_right), null, Modifier.size(16.dp),
            colorFilter = ColorFilter.tint(SettingsRed))
        Text(label, Modifier.weight(1f), color = SettingsRed.copy(alpha = if (onClick == null) .65f else 1f), fontSize = 16.sp)
        SettingsAsset(icon, tint = SettingsRed)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun SettingsPresentationSheet(sheet: SettingsSheet, dismiss: () -> Unit) {
    CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
        ModalBottomSheet(onDismissRequest = dismiss,
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
            containerColor = SettingsBackground, contentColor = SettingsInk,
            shape = RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp)) {
            SettingsSheetContent(sheet, dismiss)
        }
    }
}

@Composable
internal fun SettingsSheetContent(sheet: SettingsSheet, dismiss: () -> Unit) {
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState())
        .padding(horizontal = 20.dp).padding(bottom = 20.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        when (sheet) {
            SettingsSheet.COMPANION -> {
                SheetHeading(R.drawable.single_car_icon, "Android Companion",
                    "זיהוי אוטומטי של נסיעות ברכב ועדכון Family Car Agent.")
                Text(NotConfigured, Modifier.fillMaxWidth().background(Color(0xFFE9EDF2), RoundedCornerShape(16.dp))
                    .padding(16.dp), color = SettingsSecondary, textAlign = TextAlign.Center)
                SheetOptions {
                    SettingsRow("Android Companion", R.drawable.settings_icon, chevron = true, unavailable = true)
                    SettingsDivider()
                    SettingsRow("מידע נוסף", R.drawable.info_icon, subtitle = "איך זה עובד", chevron = true, unavailable = true)
                }
                SheetClose("סגור", dismiss)
            }
            SettingsSheet.SUPPORT -> {
                SheetHeading(R.drawable.support_icon, "צור קשר לתמיכה",
                    "נתקלת בבעיה או יש לך שאלה? נשמח לעזור.")
                SheetOptions {
                    SettingsRow("שליחת מייל", R.drawable.envelope_icon, subtitle = NotConfigured,
                        chevron = true, unavailable = true)
                    SettingsDivider()
                    SettingsRow("פתיחת צ׳אט", R.drawable.chat_suppory_icon, subtitle = Unavailable,
                        chevron = true, unavailable = true)
                }
                SheetClose("סגור", dismiss)
            }
            SettingsSheet.DELETE_ACCOUNT -> {
                SheetHeading(R.drawable.trash_icon, "מחיקת חשבון",
                    "מחיקת חשבון עלולה להשפיע על הנתונים ועל המשפחה. הפעולה אינה זמינה בשלב זה.", danger = true)
                Surface(color = Color(0xFFFFEDEE), shape = RoundedCornerShape(16.dp),
                    border = BorderStroke(1.dp, Color(0xFFF5D7DA))) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        WarningRow(R.drawable.family_icon, "ההשפעה על המשפחה והחשבון תיבדק לפני אישור")
                        WarningRow(R.drawable.clock_icon, "נתונים שיימחקו עשויים שלא להיות ניתנים לשחזור")
                        WarningRow(R.drawable.privacy_icon, "מחיקה עשויה להיות בלתי הפיכה")
                    }
                }
                Button(onClick = {}, enabled = false, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                    shape = RoundedCornerShape(12.dp), colors = ButtonDefaults.buttonColors(
                        disabledContainerColor = Color(0xFFECA3A9), disabledContentColor = Color(0xFF6D343A))) {
                    Text("המשך למחיקה")
                }
                SheetClose("ביטול", dismiss)
            }
        }
    }
}

@Composable
private fun SheetHeading(icon: Int, title: String, description: String, danger: Boolean = false) {
    Box(Modifier.size(64.dp).background(if (danger) Color(0xFFFFE2E5) else Color(0xFFE7EDF4), RoundedCornerShape(18.dp)),
        contentAlignment = Alignment.Center) { SettingsAsset(icon, 52.dp, if (danger) SettingsRed else null) }
    Text(title, color = if (danger) SettingsRed else SettingsInk, fontWeight = FontWeight.Bold,
        fontSize = 21.sp, textAlign = TextAlign.Center)
    Text(description, color = if (danger) SettingsRed else SettingsSecondary, fontSize = 14.sp,
        lineHeight = 20.sp, textAlign = TextAlign.Center)
}

@Composable
private fun SheetOptions(content: @Composable ColumnScope.() -> Unit) {
    Surface(color = Color.White.copy(alpha = .7f), shape = RoundedCornerShape(16.dp), border = BorderStroke(1.dp, SettingsBorder)) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp), content = content)
    }
}

@Composable
private fun WarningRow(icon: Int, text: String) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(text, Modifier.weight(1f), color = SettingsRed, fontSize = 13.sp)
        SettingsAsset(icon, 34.dp, SettingsRed)
    }
}

@Composable
private fun SheetClose(label: String, dismiss: () -> Unit) {
    FilledTonalButton(dismiss, Modifier.fillMaxWidth().heightIn(min = 48.dp), shape = RoundedCornerShape(12.dp),
        colors = ButtonDefaults.filledTonalButtonColors(containerColor = Color(0xFFE9EDF2), contentColor = SettingsInk)) {
        Text(label, fontSize = 16.sp)
    }
}

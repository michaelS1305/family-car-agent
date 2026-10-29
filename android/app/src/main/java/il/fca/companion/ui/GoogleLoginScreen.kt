package il.fca.companion.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.*
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.*
import il.fca.companion.R

private val LoginInk: Color
    @Composable get() = fcaColor(Color(0xFF243341), FcaColorRole.TEXT)
private val LoginSecondary: Color
    @Composable get() = fcaColor(Color(0xFF637B97), FcaColorRole.SECONDARY)
internal const val LOGIN_TITLE = "מתחברים וממשיכים"
internal const val LOGIN_SUBTITLE = "כדי להשלים את החיבור והזיהוי שלכם, התחברו עם חשבונכם האישי"
internal const val LOGIN_AUTH_NOTE = "פרטי ההתחברות נשמרים ומנוהלים על ידי Supabase Auth."

internal fun loginLegalText(ink: Color = Color(0xFF112642), open: (LegalCopy) -> Unit): AnnotatedString {
    val styles = TextLinkStyles(SpanStyle(color = ink, textDecoration = TextDecoration.Underline, fontWeight = FontWeight.SemiBold))
    return buildAnnotatedString {
        append("אנו מעבדים מידע אישי כדי לספק את Family Car Agent. מידע על המטרות, הספקים והזכויות שלך מופיע ב־ ")
        withLink(LinkAnnotation.Clickable("privacy", styles) { open(PRIVACY) }) { append("מדיניות הפרטיות") }
        append(" וב־")
        withLink(LinkAnnotation.Clickable("terms", styles) { open(TERMS) }) { append("תנאי השימוש") }
        append(".")
    }
}

internal data class LoginLayout(val title: TextStyle, val subtitle: TextStyle, val secondary: TextStyle, val legalStyle: TextStyle,
    val logo: Float, val padding: Float, val gap: Float, val fixedHeight: Float, val buttonHeight: Float) {
    val authGap get() = minOf(gap * 1.2f, 10f)
    val legalGap get() = minOf(gap * .9f, 6f)
    val cardHeight get() = fixedHeight + gap * 2.9f + authGap + legalGap
}

// Measure the exact rendered strings, including linked spans, before distributing whitespace.
internal fun loginLayout(measurer: TextMeasurer, density: Density, innerWidth: Float,
                         availableHeight: Float, legal: AnnotatedString, ink: Color = Color(0xFF243341),
                         secondaryInk: Color = Color(0xFF637B97), noteInk: Color = Color(0xFF6B7785)): LoginLayout {
    val widthPx = with(density) { innerWidth.dp.roundToPx() }
    fun style(size: Float, line: Float, weight: FontWeight = FontWeight.Normal) = TextStyle(
        fontFamily = FontFamily.SansSerif, fontSize = size.sp, lineHeight = line.sp,
        fontWeight = weight, textAlign = TextAlign.Center, color = secondaryInk, letterSpacing = 0.sp)
    fun height(text: AnnotatedString, style: TextStyle) = with(density) {
        measurer.measure(text, style, constraints = Constraints(maxWidth = widthPx)).size.height.toDp().value
    }
    var result: LoginLayout? = null
    for (compact in listOf(false, true)) {
        var titleSize = if (compact) 26f else 30f
        var title = style(titleSize, titleSize * 1.25f, FontWeight.Bold).copy(color = ink)
        while (measurer.measure(LOGIN_TITLE, title, softWrap = false).size.width > widthPx && titleSize > 20f) {
            titleSize -= .5f
            title = style(titleSize, titleSize * 1.25f, FontWeight.Bold).copy(color = ink)
        }
        val subtitle = style(if (compact) 15f else 17f, if (compact) 22f else 26f)
        val secondary = style(if (compact) 11f else 11.5f, if (compact) 15f else 16f)
            .copy(color = noteInk)
        val legalStyle = style(if (compact) 11f else 11.5f, if (compact) 15f else 16f)
            .copy(color = noteInk)
        val logo = if (compact) 70f else 114f
        val padding = if (compact) 10f else 18f
        // Existing Google asset is 720 x 160: preserve its proportions and actually use the card width.
        val buttonHeight = maxOf(48f, innerWidth / 4.5f)
        val fixed = logo + buttonHeight + padding * 2 + height(AnnotatedString(LOGIN_TITLE), title) +
            height(AnnotatedString(LOGIN_SUBTITLE), subtitle) + height(AnnotatedString(LOGIN_AUTH_NOTE), secondary) + height(legal, legalStyle)
        val gap = ((availableHeight - fixed) / 5f).coerceIn(0f, if (compact) 14f else 24f)
        result = LoginLayout(title, subtitle, secondary, legalStyle, logo, padding, gap, fixed, buttonHeight)
        if (fixed + 5 * 8f <= availableHeight) return result
    }
    return requireNotNull(result)
}

@Composable internal fun GoogleLoginScreen(modifier: Modifier, enabled: Boolean, login: () -> Unit,
                                           back: () -> Unit, openLegal: (LegalCopy) -> Unit) {
    val measurer = rememberTextMeasurer()
    val density = LocalDensity.current
    val legal = loginLegalText(fcaColor(Color(0xFF112642), FcaColorRole.TEXT), openLegal)
    BoxWithConstraints(modifier.fillMaxWidth(), contentAlignment = Alignment.TopCenter) {
        val width = minOf(maxWidth.value - 32f, 440f)
        val available = maxHeight.value - 64f
        val layout = loginLayout(measurer, density, width - 32f, available, legal, LoginInk, LoginSecondary, fcaColor(Color(0xFF6B7785), FcaColorRole.SECONDARY))
        Column(Modifier.width(width.dp).fillMaxHeight(), horizontalAlignment = Alignment.CenterHorizontally) {
            Spacer(Modifier.height(8.dp))
            Box(Modifier.fillMaxWidth().height(48.dp), contentAlignment = Alignment.Center) {
                Text("התחברות", fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = fcaColor(Color(0xFF53677D), FcaColorRole.SECONDARY))
                OutlinedIconButton(onClick = back, enabled = enabled, modifier = Modifier.size(48.dp)
                    .align(Alignment.CenterStart).semantics { contentDescription = "חזרה" },
                    shape = RoundedCornerShape(14.dp), border = BorderStroke(1.dp, fcaColor(Color(0xFFE5E3E0), FcaColorRole.BORDER))) {
                    Text("→", fontSize = 25.sp, color = LoginInk)
                }
            }
            // Center the card in the remaining viewport; compact screens spend space on content first.
            Spacer(Modifier.weight(1f))
            OutlinedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(26.dp),
                border = BorderStroke(1.dp, fcaColor(Color(0xFFEAE8E5), FcaColorRole.BORDER)),
                colors = CardDefaults.outlinedCardColors(containerColor = fcaColor(Color.White, FcaColorRole.SURFACE))) {
                Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = layout.padding.dp),
                    horizontalAlignment = Alignment.CenterHorizontally) {
                    Image(painterResource(R.drawable.fca_logo), null, Modifier.size(layout.logo.dp), contentScale = ContentScale.Fit)
                    LoginGap(layout.gap * .8f)
                    Text(LOGIN_TITLE, Modifier.fillMaxWidth(), style = layout.title)
                    LoginGap(layout.gap * .8f)
                    Text(LOGIN_SUBTITLE, Modifier.fillMaxWidth(), style = layout.subtitle)
                    LoginGap(layout.gap * 1.3f)
                    Surface(onClick = login, enabled = enabled, shape = RoundedCornerShape(50), color = fcaColor(Color.White, FcaColorRole.SURFACE),
                        modifier = Modifier.fillMaxWidth().height(layout.buttonHeight.dp).semantics { contentDescription = "התחברות באמצעות Google" }) {
                        Image(painterResource(R.drawable.google_sign_in), null, Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
                    }
                    LoginGap(layout.authGap)
                    Text(LOGIN_AUTH_NOTE, Modifier.fillMaxWidth(), style = layout.secondary)
                    LoginGap(layout.legalGap)
                    Text(legal, Modifier.fillMaxWidth(), style = layout.legalStyle)
                }
            }
            Spacer(Modifier.weight(1f))
            Spacer(Modifier.height(8.dp))
        }
    }
}

@Composable private fun LoginGap(height: Float) { Spacer(Modifier.height(height.dp)) }

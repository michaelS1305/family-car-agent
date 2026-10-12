package il.fca.companion.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import il.fca.companion.R

internal const val INTRO_HERO = "הדרך החכמה\nלנהל את הרכב המשפחתי"
internal const val INTRO_BODY = "בדקו מי עם הרכב, נהלו הזמנות וקבלו עדכונים עם סוכן אישי"
private val Ink = Color(0xFF243341)

// Fit explicit lines using the actual font metrics (including the user's font scale),
// not character counts. softWrap=false is used only for these measured explicit lines.
internal fun introTextStyle(measurer: TextMeasurer, text: String, widthPx: Int,
                            preferred: Float, weight: FontWeight): TextStyle {
    var size = preferred
    while (true) {
        val style = TextStyle(fontFamily = FontFamily.SansSerif, fontSize = size.sp,
            lineHeight = (size * 1.3f).sp, fontWeight = weight, textAlign = TextAlign.Center,
            letterSpacing = 0.sp, color = Ink)
        val measured = measurer.measure(text, style, softWrap = false)
        if (measured.size.width <= widthPx || size <= 1f) return style
        size -= 0.5f
    }
}

@Composable
internal fun IntroScreen(modifier: Modifier, enabled: Boolean, select: (LoginRoute) -> Unit) {
    val measurer = rememberTextMeasurer()
    val density = LocalDensity.current
    BoxWithConstraints(modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        val width = minOf(maxWidth.value, 440f) - 32f
        val compact = maxHeight.value < 560f
        val widthPx = with(density) { width.dp.roundToPx() }
        val brand = introTextStyle(measurer, "Family Car Agent", widthPx, if (compact) 30f else 34f, FontWeight.Bold)
        val hero = introTextStyle(measurer, INTRO_HERO, widthPx, if (compact) 26f else 29f, FontWeight.Bold)
        val body = TextStyle(fontFamily = FontFamily.SansSerif, fontSize = (if (compact) 15 else 16).sp,
            lineHeight = (if (compact) 22 else 25).sp, fontWeight = FontWeight.Medium,
            textAlign = TextAlign.Center, color = Color(0xFF536272))
        val labelWidth = with(density) { ((width - 10f) / 2f - 44f).dp.roundToPx() }
        val join = introTextStyle(measurer, "הצטרפות\nלמשפחה", labelWidth, 16f, FontWeight.SemiBold)
        val create = introTextStyle(measurer, "יצירת\nמשפחה", labelWidth, 16f, FontWeight.SemiBold)
        val link = introTextStyle(measurer, "כבר יש לי חשבון", widthPx - with(density) { 32.dp.roundToPx() }, 15f, FontWeight.Medium)
        fun height(text: String, style: TextStyle, wrap: Boolean = false): Float =
            with(density) { measurer.measure(text, style, softWrap = wrap,
                constraints = Constraints(maxWidth = widthPx)).size.height.toDp().value }
        val buttonHeight = maxOf(60f, height("הצטרפות\nלמשפחה", join) + 16f)
        val logoSize = if (compact) 96f else 126f
        val fixedHeight = logoSize + height("Family Car Agent", brand) + 2f + height(INTRO_HERO, hero) +
            height(INTRO_BODY, body, true) + buttonHeight + maxOf(48f, height("כבר יש לי חשבון", link) + 16f)
        // All remaining viewport height is deliberate inter-group whitespace, never scroll extent.
        val space = (maxHeight.value - fixedHeight).coerceAtLeast(0f)
        Column(Modifier.width(width.dp).fillMaxHeight(), horizontalAlignment = Alignment.CenterHorizontally) {
            Spacer(Modifier.height((space * .12f).dp))
            Image(painterResource(R.drawable.fca_logo_intro), null, Modifier.size(logoSize.dp))
            Spacer(Modifier.height((space * .07f).dp))
            Text("Family Car Agent", style = brand, softWrap = false)
            Spacer(Modifier.height((space * .13f).dp))
            Box(Modifier.size(80.dp, 2.dp).background(Color(0xFFE2DFDC), RoundedCornerShape(2.dp)))
            Spacer(Modifier.height((space * .13f).dp))
            Text(INTRO_HERO, Modifier.fillMaxWidth(), style = hero, softWrap = false)
            Spacer(Modifier.height((space * .09f).dp))
            Text(INTRO_BODY, Modifier.fillMaxWidth(), style = body)
            Spacer(Modifier.height((space * .34f).dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                IntroButton("יצירת\nמשפחה", create, true, enabled, Modifier.weight(1f).height(buttonHeight.dp)) { select(LoginRoute.CREATE_FAMILY) }
                IntroButton("הצטרפות\nלמשפחה", join, false, enabled, Modifier.weight(1f).height(buttonHeight.dp)) { select(LoginRoute.JOIN_FAMILY) }
            }
            TextButton(onClick = { select(LoginRoute.EXISTING_ACCOUNT) }, enabled = enabled) {
                Text("כבר יש לי חשבון", style = link, softWrap = false, color = Color(0xFF536A80), textDecoration = TextDecoration.Underline)
            }
            Spacer(Modifier.height((space * .12f).dp))
        }
    }
}

@Composable private fun IntroButton(label: String, style: TextStyle, create: Boolean, enabled: Boolean,
                                    modifier: Modifier, action: () -> Unit) {
    Surface(onClick = action, enabled = enabled, modifier = modifier, color = Color.White,
        shape = RoundedCornerShape(16.dp), border = BorderStroke(1.dp, Color(0xFFD9D6D2))) {
        Row(Modifier.padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Canvas(Modifier.size(22.dp)) {
                val stroke = 1.5.dp.toPx()
                val radius = size.minDimension / 2 - stroke
                drawCircle(Ink, radius, style = Stroke(stroke))
                if (create) {
                    val arm = radius * .53f
                    drawLine(Ink, Offset(center.x - arm, center.y), Offset(center.x + arm, center.y), stroke)
                    drawLine(Ink, Offset(center.x, center.y - arm), Offset(center.x, center.y + arm), stroke)
                } else {
                    drawCircle(Ink, radius * .27f, Offset(center.x, center.y - radius * .4f), style = Stroke(stroke))
                    drawOval(Ink, Offset(center.x - radius * .4f, center.y + radius * .08f), Size(radius * .8f, radius * .65f), style = Stroke(stroke))
                }
            }
            Spacer(Modifier.width(6.dp))
            Text(label, Modifier.weight(1f), style = style, softWrap = false)
        }
    }
}

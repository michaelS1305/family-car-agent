package il.fca.companion.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.*
import androidx.compose.ui.AbsoluteAlignment
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.*
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.*
import il.fca.companion.R
import kotlin.math.cos
import kotlin.math.sin

internal enum class DashboardCategory(val label: String, val asset: Int,
                                      val anchorX: Float, val anchorY: Float) {
    FAMILY("משפחה", R.drawable.family_icon, .50f, .20f),
    VEHICLES("רכבים", R.drawable.vehicles_icon, .77f, .44f),
    SETTINGS("הגדרות", R.drawable.settings_icon, .67f, .73f),
    HISTORY("היסטוריה", R.drawable.history_icon, .35f, .75f),
    BOOKING_CENTER("מרכז הזמנות", R.drawable.booking_center_icon, .19f, .39f)
}

internal fun dashboardGreeting(name: String): String {
    val firstName = name.trim().split(Regex("[\\s\\p{Z}]+"), limit = 2).firstOrNull().orEmpty()
    return if (firstName.isEmpty()) "היי" else "היי, $firstName"
}

private val DashboardInk = Color(0xFF243341)
private val DashboardBackground = Color(0xFFF6F7F7)

@Composable
internal fun DashboardScreen(name: String, openCategory: (DashboardCategory) -> Unit,
                             logout: () -> Unit, logoutBusy: Boolean, logoutError: String?) {
    BoxWithConstraints(Modifier.fillMaxSize().background(DashboardBackground)) {
        val compact = maxHeight < 540.dp
        Column(Modifier.fillMaxSize().padding(horizontal = 8.dp, vertical = 4.dp),
            horizontalAlignment = Alignment.CenterHorizontally) {
            Image(painterResource(R.drawable.fca_header_wordmark), "Family Car Agent",
                Modifier.widthIn(max = 255.dp).fillMaxWidth().height(if (compact) 64.dp else 85.dp)
                    .scale(.9f).graphicsLayer {
                        compositingStrategy = CompositingStrategy.Offscreen
                        blendMode = BlendMode.Multiply
                    })
            Text(dashboardGreeting(name), color = DashboardInk,
                fontSize = if (compact) 24.sp else 28.sp, fontWeight = FontWeight.Bold,
                textAlign = TextAlign.Center, maxLines = 2)
            BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
                val diameter = minOf(maxWidth, maxHeight - 70.dp -
                    (if (logoutError != null) 32.dp else 0.dp)).coerceAtLeast(0.dp)
                Column(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally) {
                    Spacer(Modifier.height(6.dp))
                    DashboardWheel(diameter, openCategory)
                    Column(Modifier.weight(1f).fillMaxWidth(),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.Center) {
                        if (logoutError != null) {
                            Text(logoutError, color = DashboardInk, fontSize = 12.sp, textAlign = TextAlign.Center)
                        }
                        TextButton(onClick = logout, enabled = !logoutBusy,
                            modifier = Modifier.widthIn(min = 144.dp).height(48.dp)
                                .background(Color.White.copy(alpha = .65f), RoundedCornerShape(50))
                                .border(1.dp, Color.White, RoundedCornerShape(50))) {
                            Image(painterResource(R.drawable.logout_icon), null, Modifier.size(36.dp))
                            Spacer(Modifier.width(4.dp))
                            Text("התנתקות", color = DashboardInk, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun DashboardWheel(diameter: Dp, openCategory: (DashboardCategory) -> Unit) {
    Box(Modifier.size(diameter).drawWithCache {
        val center = Offset(size.width / 2f, size.height / 2f)
        val radius = size.minDimension * .46f
        val hub = radius * .23f
        val bounds = Rect(center - Offset(radius, radius), center + Offset(radius, radius))
        val sectors = (0 until 5).map { index ->
            Path().apply {
                moveTo(center.x, center.y)
                arcTo(bounds, -126f + index * 72f, 72f, false)
                close()
            }
        }
        val body = Brush.linearGradient(listOf(Color.White.copy(alpha = .9f), Color(0xFFE4EBEF),
            Color.White.copy(alpha = .8f)), Offset.Zero, Offset(size.width, size.height))
        val depth = Brush.radialGradient(listOf(Color(0xFF637B97).copy(alpha = .16f), Color.Transparent),
            center + Offset(0f, radius * .06f), radius * 1.1f)
        val hubFill = Brush.linearGradient(listOf(Color.White, Color(0xFFE4EBEF)),
            center - Offset(hub, hub), center + Offset(hub, hub))
        onDrawBehind {
            drawCircle(depth, radius * 1.1f, center + Offset(0f, radius * .06f))
            drawCircle(body, radius)
            sectors.forEachIndexed { index, path ->
                drawPath(path, Color.White.copy(alpha = if (index % 2 == 0) .12f else .04f))
            }
            repeat(5) { index ->
                val angle = Math.toRadians((-126.0 + index * 72.0))
                val vector = Offset(cos(angle).toFloat(), sin(angle).toFloat())
                drawLine(Color.White.copy(alpha = .8f), center + vector * hub,
                    center + vector * radius, strokeWidth = 1.dp.toPx())
            }
            drawCircle(Color.White.copy(alpha = .7f), radius, style = Stroke(radius * .012f))
            drawCircle(Color.White.copy(alpha = .45f), radius * 1.05f, style = Stroke(1.dp.toPx()))
            drawCircle(Color(0xFF637B97).copy(alpha = .1f), hub * 1.15f, center + Offset(0f, hub * .07f))
            drawCircle(hubFill, hub)
            drawCircle(Color.White.copy(alpha = .85f), hub, style = Stroke(hub * .12f))
        }
    }) {
        val targetWidth = (diameter * .25f).coerceAtLeast(48.dp)
        val targetHeight = (diameter * .28f).coerceAtLeast(48.dp)
        DashboardCategory.entries.forEach { category ->
            Box(Modifier.align(AbsoluteAlignment.TopLeft)
                .absoluteOffset(x = diameter * category.anchorX - targetWidth / 2,
                    y = diameter * category.anchorY - targetHeight / 2)
                .size(targetWidth, targetHeight)) {
                DashboardIcon(category, diameter * .5f) { openCategory(category) }
            }
        }
    }
}

@Composable
private fun DashboardIcon(category: DashboardCategory, visibleSize: Dp, onClick: () -> Unit) {
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    Box(Modifier.fillMaxSize().background(
        if (pressed) Color.White.copy(alpha = .4f) else Color.Transparent, CircleShape)
        .clickable(interactionSource = interaction, indication = null, role = Role.Button, onClick = onClick)
        .semantics { contentDescription = category.label }, contentAlignment = Alignment.Center) {
        // Preserve the complete square PNG, including its transparent margins.
        // Only transparent padding extends beyond the non-overlapping touch target.
        Image(painterResource(category.asset), null,
            Modifier.requiredSize(visibleSize).offset(y = -visibleSize * .07f)
                .graphicsLayer { alpha = if (pressed) .82f else 1f })
    }
}

@Composable
internal fun DashboardCategoryPlaceholder(category: DashboardCategory, back: () -> Unit) {
    Column(Modifier.fillMaxSize().background(DashboardBackground).padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Text(category.label, color = DashboardInk, fontSize = 26.sp, fontWeight = FontWeight.SemiBold)
        Text("בקרוב", color = Color(0xFF637B97), fontSize = 16.sp)
        TextButton(onClick = back) { Text("חזרה לדשבורד", color = DashboardInk) }
    }
}

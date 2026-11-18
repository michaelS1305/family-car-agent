package il.fca.companion.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import il.fca.companion.R

internal fun blockingInitialLoadError(loading: Boolean, failed: Boolean, usableData: Boolean) =
    !loading && failed && !usableData

/** Presentation only. Callers supply safe copy and existing recovery actions, never exceptions. */
@Composable
internal fun FcaErrorScreen(message: String, retry: (() -> Unit)? = null,
                            secondaryLabel: String? = null, secondary: (() -> Unit)? = null) {
    val ink = fcaColor(Color(0xFF23364E), FcaColorRole.TEXT)
    CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
        BoxWithConstraints(Modifier.fillMaxSize().background(fcaColor(Color(0xFFF6F7F7), FcaColorRole.BACKGROUND)).safeDrawingPadding()) {
            val viewportHeight = maxHeight
            Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).heightIn(min = maxHeight)
                .padding(horizontal = 24.dp, vertical = 24.dp),
                horizontalAlignment = Alignment.CenterHorizontally) {
                val wordmarkBlend = if (LocalFcaDark.current) BlendMode.SrcOver else BlendMode.Multiply
                Image(painterResource(if (LocalFcaDark.current) R.drawable.family_car_agent_road_logo_1__dark else R.drawable.fca_header_wordmark), "Family Car Agent",
                    Modifier.widthIn(max = 260.dp).fillMaxWidth().height(86.dp).graphicsLayer {
                        compositingStrategy = CompositingStrategy.Offscreen
                        blendMode = wordmarkBlend
                    })
                Spacer(Modifier.height(if (viewportHeight < 500.dp) 20.dp else 64.dp))
                // Preserve the original navy glyph in light mode; use a readable control tint in dark.
                Image(painterResource(R.drawable.warning_icon), null, Modifier.size(112.dp), colorFilter = fcaControlIconFilter())
                Spacer(Modifier.height(16.dp))
                Text("משהו השתבש", color = ink, fontSize = 26.sp, fontWeight = FontWeight.Bold,
                    modifier = Modifier.semantics { heading() }, textAlign = TextAlign.Center)
                Spacer(Modifier.height(12.dp))
                Text(message, color = fcaColor(Color(0xFF637B97), FcaColorRole.SECONDARY), fontSize = 16.sp, lineHeight = 24.sp,
                    textAlign = TextAlign.Center, modifier = Modifier.widthIn(max = 360.dp))
                Spacer(Modifier.height(32.dp))
                if (retry != null) Button(retry,
                    modifier = Modifier.widthIn(max = 340.dp).fillMaxWidth().heightIn(min = 52.dp),
                    shape = RoundedCornerShape(16.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = ink, contentColor = fcaColor(Color.White, FcaColorRole.ON_ACTION))) {
                    Text("נסה שוב")
                }
                if (secondary != null && secondaryLabel != null) {
                    Spacer(Modifier.height(12.dp))
                    OutlinedButton(secondary,
                        modifier = Modifier.widthIn(max = 340.dp).fillMaxWidth().heightIn(min = 52.dp),
                        shape = RoundedCornerShape(16.dp),
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = ink)) { Text(secondaryLabel) }
                }
            }
        }
    }
}

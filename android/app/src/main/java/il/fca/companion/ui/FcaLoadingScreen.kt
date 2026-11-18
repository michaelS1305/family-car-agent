package il.fca.companion.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.fadeOut
import androidx.compose.animation.core.*
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.dp
import il.fca.companion.R

internal fun bootstrapLoading(screen: EntryScreen, busy: Boolean) =
    screen == EntryScreen.BOOTSTRAP && busy

/** Presentation only: destination composition is never delayed by this exit animation. */
@Composable
internal fun FcaLoadingOverlay(loading: Boolean) {
    AnimatedVisibility(visible = loading, enter = EnterTransition.None,
        exit = fadeOut(tween(160))) {
        FcaLoadingScreen(loading)
    }
}

@Composable
private fun FcaLoadingScreen(loading: Boolean) {
    val appearance = remember { Animatable(0f) }
    var appeared by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        appearance.animateTo(1f, tween(400))
        appeared = true
    }
    val breathing = rememberInfiniteTransition(label = "loading breathing")
    val breath by breathing.animateFloat(1f, .84f,
        infiniteRepeatable(tween(1800), RepeatMode.Reverse), label = "logo alpha")
    Box(Modifier.fillMaxSize().background(fcaColor(Color(0xFFF6F7F7), FcaColorRole.BACKGROUND))
        .clearAndSetSemantics {
            // A stable description, not a live region; no announcements on animation frames.
            if (loading) {
                contentDescription = "טוען"
                progressBarRangeInfo = ProgressBarRangeInfo.Indeterminate
            }
        }) {
        BoxWithConstraints(Modifier.fillMaxSize().safeDrawingPadding()) {
            val logoSize = minOf(144.dp, maxWidth * .36f, maxHeight * .28f)
            Image(painterResource(R.drawable.fca_logo_intro), null,
                Modifier.align(Alignment.Center).size(logoSize).graphicsLayer {
                    alpha = appearance.value * if (appeared) breath else 1f
                })
            LinearProgressIndicator(
                modifier = Modifier.align(Alignment.Center)
                    .offset(y = logoSize / 2 + 48.dp).width(120.dp).height(4.dp)
                    .clip(RoundedCornerShape(50)),
                color = fcaColor(Color(0xFF637B97), FcaColorRole.SECONDARY), trackColor = fcaColor(Color(0xFFE0E5E7), FcaColorRole.BORDER))
        }
    }
}

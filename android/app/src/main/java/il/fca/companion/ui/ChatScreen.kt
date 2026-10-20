
package il.fca.companion.ui

import android.graphics.RenderEffect
import android.graphics.RuntimeShader
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.AbsoluteAlignment
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.asComposeRenderEffect
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDirection
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import il.fca.companion.R
import il.fca.companion.net.ChatFailure
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlinx.coroutines.delay
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll

/**
 * Presentation model only; no fixture conversations, persistence or API calls.
 */
internal data class ChatMessagePresentation(
    val text: String,
    val timestamp: String,
    val fromUser: Boolean
)

@Composable
internal fun ChatScreen(
    state: ChatState,
    send: (String) -> Boolean,
    retry: () -> Boolean,
    reloadHistory: () -> Unit,
    userName: String,
) {
    val ink = Color(0xFF243341)
    val density = LocalDensity.current
    val scroll = rememberScrollState()
    val scrollPolicy = remember { ChatScrollPolicy() }
    val threshold = with(density) { 48.dp.roundToPx() }
    val userScroll = remember(scroll, threshold) {
        object : NestedScrollConnection {
            override fun onPreScroll(available: Offset, source: NestedScrollSource): Offset {
                if (source == NestedScrollSource.UserInput && available.y > 0)
                    scrollPolicy.userScrolled(Int.MAX_VALUE, threshold)
                return Offset.Zero
            }
            override fun onPostScroll(consumed: Offset, available: Offset, source: NestedScrollSource): Offset {
                if (source == NestedScrollSource.UserInput)
                    scrollPolicy.userScrolled(scroll.maxValue - scroll.value, threshold)
                return Offset.Zero
            }
        }
    }
    val currentState by rememberUpdatedState(state)
    LaunchedEffect(scroll) {
        var previousKeys = emptyList<String>()
        var previousMax = 0
        var pendingPrepend = false
        snapshotFlow {
            Triple(currentState.messages.map { it.message.requestId + ":" + it.message.role },
                currentState.historyLoaded || currentState.messages.isNotEmpty(), scroll.maxValue)
        }.collect { (keys, ready, maximum) ->
            if (maximum == Int.MAX_VALUE) return@collect // Not measured yet.
            if (previousKeys.isNotEmpty() && keys.size > previousKeys.size &&
                keys.takeLast(previousKeys.size) == previousKeys) pendingPrepend = true
            val follow = scrollPolicy.update(keys, ready)
            if (pendingPrepend) {
                if (maximum != previousMax) {
                    scroll.scrollTo((scroll.value + maximum - previousMax).coerceAtLeast(0))
                    pendingPrepend = false
                }
            } else if (follow) {
                // Immediate positioning avoids fighting the user's drag with a long animation.
                scroll.scrollTo(maximum)
            }
            previousKeys = keys
            previousMax = maximum
        }
    }
    val headerHeight = with(density) {
        WindowInsets.safeDrawing.getTop(this).toFloat() + 89.dp.toPx()
    }
    val maxBlurRadius = with(density) { 6.dp.toPx() }
    val headerBlur = remember(headerHeight, maxBlurRadius) {
        fun pass(x: Float, y: Float): RenderEffect {
            val shader = RuntimeShader(HeaderBlurShader).apply {
                setFloatUniform("headerHeight", headerHeight)
                setFloatUniform("maxRadius", maxBlurRadius)
                setFloatUniform("direction", x, y)
            }
            return RenderEffect.createRuntimeShaderEffect(shader, "content")
        }
        RenderEffect.createChainEffect(
            pass(0f, 1f),
            pass(1f, 0f)
        ).asComposeRenderEffect()
    }

    val messages = state.messages.map {
        ChatMessagePresentation(
            it.message.content,
            DateTimeFormatter
                .ofPattern("HH:mm")
                .withZone(ZoneId.systemDefault())
                .format(Instant.parse(it.message.timestamp)),
            it.message.role == "user"
        )
    }

    var retryReady by remember(state.retryNotBefore) {
        mutableStateOf(
            System.currentTimeMillis() >= (state.retryNotBefore ?: 0)
        )
    }

    LaunchedEffect(state.retryNotBefore) {
        delay(
            ((state.retryNotBefore ?: 0) - System.currentTimeMillis())
                .coerceAtLeast(0)
        )
        retryReady = true
    }

    var draft by remember {
        mutableStateOf("")
    }

    Box(
        modifier = Modifier.fillMaxSize()
    ) {
        Column(
            modifier = Modifier.fillMaxSize()
        ) {
            // Conversation area.
            // The top space is inside the scrollable content rather than
            // being a separate header row, so messages can move behind the
            // fixed wordmark/header treatment while scrolling.
            Column(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .drawWithContent {
                        drawContent()

                        // Bottom viewport overlay remains unchanged.
                        val fade = minOf(
                            36.dp.toPx(),
                            size.height / 2f
                        )

                        val background = Color(0xFFF6F7F7)

                        if (fade > 0f) {
                            drawRect(
                                brush = Brush.verticalGradient(
                                    0f to background.copy(alpha = 0f),
                                    .55f to background.copy(alpha = .55f),
                                    1f to background.copy(alpha = .94f),
                                    startY = size.height - fade,
                                    endY = size.height
                                ),
                                topLeft = Offset(
                                    0f,
                                    size.height - fade
                                ),
                                size = Size(
                                    size.width,
                                    fade
                                )
                            )
                        }
                    }
                    // Only this conversation layer is sampled. The fixed wordmark,
                    // composer and bottom fade are outside the effect.
                    .graphicsLayer { renderEffect = headerBlur }
                    .nestedScroll(userScroll)
                    .verticalScroll(scroll)
                    .padding(horizontal = 16.dp)
                    .padding(
                        top = WindowInsets.safeDrawing
                            .asPaddingValues()
                            .calculateTopPadding() + 93.dp
                    ),
                verticalArrangement =
                    if (messages.isEmpty()) {
                        Arrangement.Bottom
                    } else {
                        Arrangement.spacedBy(12.dp)
                    }
            ) {
                if (
                    state.historyLoading ||
                    !state.historyLoaded &&
                    state.historyError == null
                ) {
                    Text(
                        text = "...",
                        modifier = Modifier.align(
                            Alignment.CenterHorizontally
                        ),
                        color = ink
                    )
                }

                state.historyError?.let {
                    Text(
                        text = "לא ניתן לטעון את השיחה כרגע",
                        color = ink,
                        fontSize = 12.sp
                    )

                    TextButton(
                        onClick = reloadHistory,
                        enabled = !state.historyLoading
                    ) {
                        Text("נסה שוב")
                    }
                }

                messages.forEachIndexed { index, message ->
                    Column(
                        modifier = Modifier
                            .align(
                                if (message.fromUser) {
                                    Alignment.Start
                                } else {
                                    Alignment.End
                                }
                            )
                            .widthIn(
                                max = 264.dp
                            )
                    ) {
                        Text(
                            text = message.text,
                            modifier = Modifier
                                .background(
                                    color =
                                        if (message.fromUser) {
                                            ink
                                        } else {
                                            Color(0xFFE9EEF0)
                                        },
                                    shape = RoundedCornerShape(
                                        18.dp
                                    )
                                )
                                .padding(
                                    horizontal = 11.dp,
                                    vertical = 9.dp
                                ),
                            color =
                                if (message.fromUser) {
                                    Color.White
                                } else {
                                    ink
                                },
                            fontSize = 14.sp,
                            lineHeight = 20.sp
                        )

                        CompositionLocalProvider(
                            LocalLayoutDirection provides
                                    if (message.fromUser) {
                                        LocalLayoutDirection.current
                                    } else {
                                        LayoutDirection.Ltr
                                    }
                        ) {
                            Row(
                                modifier =
                                    if (message.fromUser) {
                                        Modifier
                                    } else {
                                        Modifier.align(
                                            AbsoluteAlignment.Left
                                        )
                                    },
                                verticalAlignment =
                                    Alignment.CenterVertically
                            ) {
                                if (!message.fromUser) {
                                    Image(
                                        painter = painterResource(
                                            R.drawable.fca_logo
                                        ),
                                        contentDescription = null,
                                        modifier = Modifier
                                            .padding(
                                                top = 4.dp
                                            )
                                            .size(
                                                26.dp
                                            )
                                            .background(
                                                Color.White,
                                                CircleShape
                                            )
                                    )
                                } else {
                                    UserAvatar(
                                        name = userName,
                                        size = 26.dp,
                                        modifier = Modifier.padding(top = 4.dp)
                                    )
                                }

                                Text(
                                    text = message.timestamp,
                                    modifier = Modifier.padding(
                                        5.dp
                                    ),
                                    fontSize = 10.sp,
                                    color = Color(
                                        0xFF637B97
                                    )
                                )
                            }
                        }
                    }

                    if (
                        state.messages[index].delivery ==
                        ChatDisplayMessage.Delivery.FAILED
                    ) {
                        Text(
                            text = "ההודעה לא הושלמה",
                            color = ink,
                            fontSize = 12.sp
                        )
                    }
                }

                if (state.sending) {
                    Text(
                        text = "...",
                        modifier = Modifier
                            .align(
                                Alignment.End
                            )
                            .widthIn(
                                max = 264.dp
                            )
                            .background(
                                Color(0xFFE9EEF0),
                                RoundedCornerShape(
                                    18.dp
                                )
                            )
                            .padding(
                                horizontal = 11.dp,
                                vertical = 9.dp
                            ),
                        color = ink,
                        fontSize = 14.sp
                    )
                }

                state.error?.let { failure ->
                    Text(
                        text =
                            if (
                                failure.kind ==
                                ChatFailure.Kind.AUTH
                            ) {
                                "לא ניתן לאמת את ההתחברות כרגע"
                            } else {
                                "לא ניתן להשלים את הבקשה כרגע"
                            },
                        color = ink,
                        fontSize = 12.sp
                    )

                    if (
                        state.pendingRequest != null &&
                        failure.retryable
                    ) {
                        TextButton(
                            onClick = {
                                if (retry()) scrollPolicy.sent()
                            },
                            enabled =
                                retryReady &&
                                        !state.sending
                        ) {
                            Text(
                                if (retryReady) {
                                    "נסה שוב"
                                } else {
                                    "אפשר לנסות שוב בעוד רגע"
                                }
                            )
                        }
                    }
                }

                // Suggestions
                if (state.showSuggestions()) {
                    Column(
                        modifier = Modifier
                            .align(
                                AbsoluteAlignment.Right
                            )
                            .fillMaxWidth(
                                0.8f
                            )
                            .padding(
                                bottom = 20.dp
                            ),
                        verticalArrangement =
                            Arrangement.spacedBy(
                                8.dp
                            )
                    ) {
                        listOf(
                            "מי משתמש ברכב כרגע?",
                            "אילו רכבים פנויים עכשיו?",
                            "אני צריך להזמין את הרכב"
                        ).forEach { suggestion ->
                            CompositionLocalProvider(
                                LocalLayoutDirection provides
                                        LayoutDirection.Rtl
                            ) {
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .height(
                                            44.dp
                                        )
                                        .clip(
                                            RoundedCornerShape(
                                                15.dp
                                            )
                                        )
                                        .background(
                                            Color.White.copy(
                                                alpha = 0.65f
                                            )
                                        )
                                        .border(
                                            width = 1.dp,
                                            color = Color(
                                                0xFFD9DEE7
                                            ),
                                            shape =
                                                RoundedCornerShape(
                                                    15.dp
                                                )
                                        )
                                        .clickable {
                                            draft = suggestion
                                        }
                                        .padding(
                                            horizontal = 10.dp
                                        ),
                                    verticalAlignment =
                                        Alignment.CenterVertically
                                ) {
                                    Text(
                                        text = "‹",
                                        color = ink,
                                        fontSize = 18.sp
                                    )

                                    Spacer(
                                        modifier = Modifier.width(
                                            4.dp
                                        )
                                    )

                                    Text(
                                        text = suggestion,
                                        modifier = Modifier.weight(
                                            1f
                                        ),
                                        color = ink,
                                        fontSize = 9.sp,
                                        textAlign =
                                            TextAlign.Right,
                                        maxLines = 1,
                                        softWrap = false
                                    )
                                }
                            }
                        }
                    }
                }
            }

            // Composer
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(
                        horizontal = 14.dp,
                        vertical = 4.dp
                    ),
                verticalAlignment =
                    Alignment.CenterVertically
            ) {
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .height(
                            52.dp
                        )
                        .background(
                            Color.White.copy(
                                alpha = 0.9f
                            ),
                            RoundedCornerShape(
                                28.dp
                            )
                        )
                        .border(
                            width = 1.dp,
                            color = Color(
                                0xFFE0E5E7
                            ),
                            shape =
                                RoundedCornerShape(
                                    28.dp
                                )
                        )
                        .padding(
                            horizontal = 18.dp
                        ),
                    contentAlignment =
                        Alignment.CenterStart
                ) {
                    BasicTextField(
                        value = draft,
                        onValueChange = {
                            draft = it
                        },
                        modifier = Modifier
                            .fillMaxWidth(),
                        singleLine = true,
                        textStyle = TextStyle(
                            color = ink,
                            fontSize = 15.sp,
                            textDirection =
                                TextDirection.ContentOrRtl
                        ),
                        cursorBrush =
                            SolidColor(ink),
                        decorationBox = {
                                innerTextField ->
                            Box {
                                if (draft.isEmpty()) {
                                    Text(
                                        text =
                                            "איך אפשר לעזור..",
                                        color = Color(
                                            0xFF7B8995
                                        ),
                                        fontSize =
                                            15.sp
                                    )
                                }

                                innerTextField()
                            }
                        }
                    )
                }

                Spacer(
                    modifier = Modifier.width(
                        10.dp
                    )
                )

                IconButton(
                    onClick = {
                        if (
                            state.canSend(draft)
                        ) {
                            draft =
                                draftAfterChatSend(
                                    draft,
                                    { text -> send(text).also { if (it) scrollPolicy.sent() } }
                                )
                        }
                    },
                    enabled =
                        state.canSend(draft),
                    modifier = Modifier
                        .size(
                            48.dp
                        )
                        .background(
                            if (
                                state.canSend(draft)
                            ) {
                                ChatSendActive
                            } else {
                                ChatSendInactive
                            },
                            CircleShape
                        )
                ) {
                    Image(
                        painter = painterResource(
                            R.drawable.ic_send
                        ),
                        contentDescription =
                            "שליחה",
                        modifier = Modifier.size(
                            28.dp
                        )
                    )
                }
            }
        }

        // Fixed wordmark overlay.
        // It no longer occupies a separate header row.
        Box(
            modifier = Modifier
                .align(
                    Alignment.TopCenter
                )
                .fillMaxWidth()
                .windowInsetsPadding(
                    WindowInsets.safeDrawing.only(
                        WindowInsetsSides.Top
                    )
                )
                .padding(
                    horizontal = 16.dp,
                    vertical = 4.dp
                ),
            contentAlignment =
                Alignment.Center
        ) {
            Image(
                painter = painterResource(
                    R.drawable.fca_header_wordmark
                ),
                contentDescription =
                    "Family Car Agent",
                modifier = Modifier
                    .widthIn(
                        max = 255.dp
                    )
                    .fillMaxWidth()
                    .height(
                        85.dp
                    )
                    .scale(
                        0.9f
                    )
                    .graphicsLayer {
                        compositingStrategy =
                            CompositingStrategy.Offscreen
                        blendMode =
                            BlendMode.Multiply
                    }
            )
        }
    }
}

private val ChatSendInactive =
    Color(0xFFDDE5EA)

private val ChatSendActive =
    Color(0xFFB6C7D3)

// Two separable nine-tap Gaussian-like passes. The radius varies smoothly per
// pixel: 0 at the wordmark bottom, 16dp at the window top. This is a sampled
// approximation to a spatially varying Gaussian, not a uniform blur/scrim.
// Pixels below the header return their input unchanged in BOTH passes.
private const val HeaderBlurShader = """
uniform shader content;
uniform float headerHeight;
uniform float maxRadius;
uniform float2 direction;

half4 main(float2 p) {
    if (p.y >= headerHeight) {
        return content.eval(p);
    }
    float progress = clamp(1.0 - p.y / headerHeight, 0.0, 1.0);
    float radius = maxRadius * progress * progress * (3.0 - 2.0 * progress);
    float2 step = direction * radius * 0.5;
    half4 color = content.eval(p) * 0.204162;
    color += (content.eval(p - step) + content.eval(p + step)) * 0.180174;
    color += (content.eval(p - step * 2.0) + content.eval(p + step * 2.0)) * 0.123832;
    color += (content.eval(p - step * 3.0) + content.eval(p + step * 3.0)) * 0.066282;
    color += (content.eval(p - step * 4.0) + content.eval(p + step * 4.0)) * 0.027631;
    return color;
}
"""

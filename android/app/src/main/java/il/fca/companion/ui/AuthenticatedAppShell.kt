package il.fca.companion.ui

import androidx.activity.compose.BackHandler
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import il.fca.companion.R

internal enum class AppMode {
    CHAT,
    DASHBOARD
}

internal class AppShellState {

    var mode by mutableStateOf(AppMode.CHAT)
        private set
    var category by mutableStateOf<DashboardCategory?>(null)
        private set

    fun select(value: AppMode) {
        category = null
        mode = value
    }
    fun openCategory(value: DashboardCategory) {
        if (mode == AppMode.DASHBOARD) category = value
    }

    fun back() {
        if (category != null) category = null else mode = AppMode.CHAT
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun AuthenticatedAppShell(chat: ChatViewModel, authenticatedName: String,
                                   logout: () -> Unit, logoutBusy: Boolean, logoutError: String?,
                                   history: HistoryViewModel, familyId: Long?, vehicles: VehiclesViewModel, family: FamilyViewModel,
                                   booking: BookingViewModel) {

    val state = remember {
        AppShellState()
    }

    /*
     * Used to hide the bottom Chat/Dashboard slider
     * while the software keyboard is visible.
     *
     * IME layout spacing for the authenticated shell
     * is handled by imePadding() on the outer Column.
     */
    val imeVisible = WindowInsets.isImeVisible
    val headerFadeHeight = with(LocalDensity.current) {
        // End near the wordmark bottom (4dp top padding + 85dp image bounds).
        WindowInsets.statusBars.getTop(this).toFloat() + 89.dp.toPx()
    }

    BackHandler(
        enabled = state.mode == AppMode.DASHBOARD
    ) {
        state.back()
    }

    Box(Modifier.fillMaxSize()) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFFF6F7F7))
            .windowInsetsPadding(
                WindowInsets.safeDrawing.only(
                    WindowInsetsSides.Horizontal
                )
            )
            .imePadding()
    ) {

        /*
         * Main application content.
         */
        Box(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
        ) {

            ChatScreen(chat.state, chat::sendMessage, chat::retryPendingRequest, chat::loadHistory)

            androidx.compose.animation.AnimatedVisibility(
                visible = state.mode == AppMode.DASHBOARD,
                modifier = Modifier.fillMaxSize().windowInsetsPadding(
                    WindowInsets.safeDrawing.only(WindowInsetsSides.Top)
                ),
                enter = fadeIn() +
                        slideInVertically {
                            it / 30
                        },
                exit = fadeOut() +
                        slideOutVertically {
                            it / 30
                        }
            ) {

                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .background(
                            Color(0xFFF6F7F7).copy(
                                alpha = 0.98f
                            )
                        ),
                    contentAlignment = Alignment.Center
                ) {

                    val category = state.category
                    if (category == null) {
                        DashboardScreen(authenticatedName, state::openCategory, logout, logoutBusy, logoutError)
                    } else if (category == DashboardCategory.HISTORY) {
                        HistoryScreen(history, familyId, state::back)
                    } else if (category == DashboardCategory.VEHICLES) {
                        VehiclesScreen(vehicles, familyId, state::back)
                    } else if (category == DashboardCategory.FAMILY) {
                        FamilyScreen(family, familyId, state::back)
                    } else if (category == DashboardCategory.BOOKING_CENTER) {
                        BookingScreen(booking, state::back)
                    } else {
                        DashboardCategoryPlaceholder(category, state::back)
                    }
                }
            }
        }

        /*
         * Bottom Chat / Dashboard slider.
         *
         * Completely removed from the layout while the IME is open.
         *
         * When the keyboard is closed, navigationBarsPadding keeps
         * the slider above Android's system navigation area.
         */
        if (!imeVisible && state.category != DashboardCategory.HISTORY && state.category != DashboardCategory.VEHICLES && state.category != DashboardCategory.FAMILY && state.category != DashboardCategory.BOOKING_CENTER) {

            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .navigationBarsPadding()
                    .padding(bottom = 2.dp)
                    .height(57.6.dp),
                contentAlignment = Alignment.Center
            ) {

                BoxWithConstraints(
                    modifier = Modifier
                        .padding(horizontal = 12.dp)
                        .scale(0.8f)
                        .widthIn(max = 340.dp)
                        .fillMaxWidth()
                        .requiredHeight(72.dp)
                        .background(
                            color = Color.White.copy(
                                alpha = 0.8f
                            ),
                            shape = RoundedCornerShape(50)
                        )
                        .border(
                            width = 1.dp,
                            color = Color(0xFFE0E5E7),
                            shape = RoundedCornerShape(50)
                        )
                ) {

                    val position by animateFloatAsState(
                        targetValue =
                            if (state.mode == AppMode.CHAT) {
                                0f
                            } else {
                                1f
                            },
                        label = "mode"
                    )

                    /*
                     * Selected half of the slider.
                     */
                    Box(
                        modifier = Modifier
                            .padding(4.dp)
                            .offset(
                                x = (maxWidth / 2) * position
                            )
                            .width(
                                maxWidth / 2 - 8.dp
                            )
                            .fillMaxHeight()
                            .background(
                                color = Color(0xFFE4EBEF),
                                shape = RoundedCornerShape(50)
                            )
                    )

                    /*
                     * Chat and Dashboard controls.
                     */
                    Row(
                        modifier = Modifier.fillMaxSize()
                    ) {

                        AppMode.entries.forEach { mode ->

                            Row(
                                modifier = Modifier
                                    .weight(1f)
                                    .fillMaxHeight()
                                    .selectable(
                                        selected = state.mode == mode,
                                        onClick = {
                                            state.select(mode)
                                        }
                                    ),
                                horizontalArrangement = Arrangement.Center,
                                verticalAlignment = Alignment.CenterVertically
                            ) {

                                Image(
                                    painter = painterResource(
                                        if (mode == AppMode.CHAT) {
                                            R.drawable.chat_icon
                                        } else {
                                            R.drawable.dashboard_icon
                                        }
                                    ),
                                    contentDescription =
                                        if (mode == AppMode.CHAT) {
                                            "צ׳אט"
                                        } else {
                                            "דשבורד"
                                        },
                                    modifier = Modifier.requiredSize(
                                        67.2.dp
                                    )
                                )
                            }
                        }
                    }
                }
            }
        }
    }
    // Sibling of the inset content: window-origin drawing without consuming any insets.
    // Multiply preserves the dark wordmark rather than washing it out with a light scrim.
    if (state.mode == AppMode.CHAT) {
        Canvas(Modifier.matchParentSize()) {
            drawRect(
                brush = Brush.verticalGradient(
                    0f to Color(0xFFE4EBEF).copy(alpha = .8f),
                    .4f to Color(0xFFE4EBEF).copy(alpha = .5f),
                    .75f to Color(0xFFE4EBEF).copy(alpha = .18f),
                    1f to Color(0xFFE4EBEF).copy(alpha = 0f),
                    endY = headerFadeHeight
                ),
                size = Size(size.width, headerFadeHeight),
                blendMode = BlendMode.Multiply
            )
        }
    }
    }
}

@Composable
private fun GaugeIcon() {

    Canvas(
        modifier = Modifier.size(24.dp)
    ) {

        val ink = Color(0xFF243341)

        drawArc(
            color = ink,
            startAngle = 150f,
            sweepAngle = 240f,
            useCenter = false,
            style = Stroke(
                width = 1.6.dp.toPx()
            )
        )

        drawLine(
            color = ink,
            start = center,
            end = Offset(
                x = size.width * 0.75f,
                y = size.height * 0.28f
            ),
            strokeWidth = 1.6.dp.toPx()
        )

        drawCircle(
            color = ink,
            radius = 1.8.dp.toPx(),
            center = center
        )
    }
}

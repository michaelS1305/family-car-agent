
package il.fca.companion.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.*
import il.fca.companion.R
import il.fca.companion.net.BookingReservation
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.YearMonth
import java.time.ZoneId

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun BookingScreen(
    model: BookingViewModel,
    back: () -> Unit
) {
    val localBack = {
        if (!model.dismiss()) back()
    }

    BackHandler(onBack = localBack)

    DisposableEffect(model) {
        model.enter()
        onDispose { model.leave() }
    }

    val data = model.visibleData
    val action = model.visibleAction
    val range = bookingRange(model.visibleMonth)
    val query = model.query
    val loaded = data.loaded == range

    val dots = remember(data.rows, data.loaded, query) {
        if (loaded) {
            bookingDots(data.rows, query)
        } else {
            emptySet()
        }
    }

    val rows = remember(
        data.rows,
        data.loaded,
        query,
        model.selectedDate
    ) {
        if (loaded) {
            bookingRows(
                data.rows,
                model.selectedDate,
                query
            )
        } else {
            emptyList()
        }
    }

    val pager = rememberPagerState(
        initialPage = model.pageOf(model.visibleMonth)
    ) {
        model.pageCount
    }

    val scope = rememberCoroutineScope()

    val today = LocalDate.now(
        ZoneId.of("Asia/Jerusalem")
    )

    LaunchedEffect(model.visibleMonth) {
        val target = model.pageOf(model.visibleMonth)

        if (pager.currentPage != target) {
            pager.scrollToPage(target)
        }
    }

    LaunchedEffect(pager) {
        snapshotFlow {
            pager.settledPage
        }
            .drop(1)
            .collect {
                model.moveToMonth(
                    model.monthAt(it)
                )
            }
    }

    CompositionLocalProvider(
        LocalLayoutDirection provides LayoutDirection.Rtl
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .background(Color(0xFFF6F7F7))
                .navigationBarsPadding(),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            VehicleProductHeader(localBack)

            BoxWithConstraints(
                Modifier
                    .weight(1f)
                    .fillMaxWidth()
            ) {
                val sheet = rememberStandardBottomSheetState(
                    initialValue = SheetValue.PartiallyExpanded,
                    skipHiddenState = true
                )

                val scaffold = rememberBottomSheetScaffoldState(
                    bottomSheetState = sheet
                )

                val blocked =
                    action.submitting ||
                            action.draft != null ||
                            action.confirmation != null ||
                            model.visibleFilters.open

                LaunchedEffect(model.sheetExpanded) {
                    if (model.sheetExpanded) {
                        sheet.expand()
                    } else {
                        sheet.partialExpand()
                    }
                }

                LaunchedEffect(sheet) {
                    snapshotFlow {
                        sheet.currentValue
                    }
                        .drop(1)
                        .collect {
                            model.expandSheet(
                                it == SheetValue.Expanded
                            )
                        }
                }

                val sheetHeight = maxHeight * .94f

                // Enough space for handle, toolbar and date.
                val peek = minOf(
                    194.dp,
                    maxHeight * .40f
                )

                BottomSheetScaffold(
                    scaffoldState = scaffold,
                    sheetPeekHeight = peek,
                    sheetSwipeEnabled = !blocked,
                    sheetContainerColor = Color(0xFFF6F7F7),
                    sheetShape = RoundedCornerShape(
                        topStart = 26.dp,
                        topEnd = 26.dp
                    ),
                    sheetShadowElevation = 5.dp,
                    sheetDragHandle = null,
                    containerColor = Color.Transparent,
                    sheetContent = {
                        BookingBookingsSheet(
                            model = model,
                            rows = rows,
                            loaded = loaded,
                            modifier = Modifier.height(sheetHeight),
                            onToday = {
                                model.selectDate(today)

                                val todayMonth = YearMonth.from(today)
                                val targetPage = model.pageOf(todayMonth)

                                scope.launch {
                                    pager.animateScrollToPage(
                                        targetPage
                                    )
                                }
                            }
                        )
                    }
                ) { padding ->

                    Column(
                        modifier = Modifier
                            .widthIn(max = 620.dp)
                            .fillMaxWidth()
                            .fillMaxSize()
                            .verticalScroll(rememberScrollState())
                            .padding(
                                bottom = padding.calculateBottomPadding()
                            )
                            .padding(
                                horizontal = 18.dp,
                                vertical = 8.dp
                            ),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(14.dp)
                    ) {
                        // Booking Center title artwork.
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(90.dp),
                            contentAlignment = Alignment.Center
                        ) {
                            Image(
                                painter = painterResource(
                                    R.drawable.booking_center_icon
                                ),
                                contentDescription = "מרכז הזמנות",
                                modifier = Modifier
                                    .requiredSize(170.dp)
                                    .offset(y = (-15).dp)
                            )
                        }

                        // Calendar panel.
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .background(
                                    Color.White.copy(alpha = .65f),
                                    RoundedCornerShape(24.dp)
                                )
                                .border(
                                    1.dp,
                                    Color(0xFFE0E5EB),
                                    RoundedCornerShape(24.dp)
                                )
                                .padding(10.dp)
                        ) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                TextButton(
                                    enabled = pager.currentPage > 0,
                                    onClick = {
                                        scope.launch {
                                            pager.animateScrollToPage(
                                                pager.currentPage - 1
                                            )
                                        }
                                    }
                                ) {
                                    Text(
                                        "‹",
                                        color = VehicleInk,
                                        fontSize = 30.sp
                                    )
                                }

                                Text(
                                    text = "${
                                        BookingMonths[
                                            model.visibleMonth.monthValue - 1
                                        ]
                                    } ${model.visibleMonth.year}",
                                    modifier = Modifier.weight(1f),
                                    color = VehicleInk,
                                    fontSize = 21.sp,
                                    fontWeight = FontWeight.Bold,
                                    textAlign = TextAlign.Center
                                )

                                TextButton(
                                    enabled = pager.currentPage <
                                            model.pageCount - 1,
                                    onClick = {
                                        scope.launch {
                                            pager.animateScrollToPage(
                                                pager.currentPage + 1
                                            )
                                        }
                                    }
                                ) {
                                    Text(
                                        "›",
                                        color = VehicleInk,
                                        fontSize = 30.sp
                                    )
                                }
                            }

                            Row(
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                listOf(
                                    "א",
                                    "ב",
                                    "ג",
                                    "ד",
                                    "ה",
                                    "ו",
                                    "ש"
                                ).forEach { weekday ->
                                    Text(
                                        text = weekday,
                                        modifier = Modifier.weight(1f),
                                        fontSize = 13.sp,
                                        fontWeight = FontWeight.Medium,
                                        color = Color(0xFF738197),
                                        textAlign = TextAlign.Center
                                    )
                                }
                            }

                            HorizontalPager(
                                state = pager,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .height(288.dp),
                                verticalAlignment = Alignment.Top
                            ) { page ->
                                val month = model.monthAt(page)

                                Column(
                                    modifier = Modifier.fillMaxWidth()
                                ) {
                                    bookingMonthDays(month)
                                        .chunked(7)
                                        .forEach { week ->

                                            // RTL Row: Sunday on the right.
                                            Row(
                                                modifier = Modifier.fillMaxWidth()
                                            ) {
                                                week.forEach { date ->
                                                    val selected =
                                                        date == model.selectedDate

                                                    Box(
                                                        modifier = Modifier
                                                            .weight(1f)
                                                            .height(48.dp),
                                                        contentAlignment =
                                                            Alignment.Center
                                                    ) {
                                                        Column(
                                                            modifier = Modifier
                                                                .size(42.dp)
                                                                .background(
                                                                    if (selected) {
                                                                        Color(
                                                                            0xFF285B9D
                                                                        )
                                                                    } else {
                                                                        Color.Transparent
                                                                    },
                                                                    CircleShape
                                                                )
                                                                .clickable {
                                                                    model.selectDate(
                                                                        date
                                                                    )
                                                                },
                                                            horizontalAlignment =
                                                                Alignment.CenterHorizontally,
                                                            verticalArrangement =
                                                                Arrangement.Center
                                                        ) {
                                                            Text(
                                                                text = date
                                                                    .dayOfMonth
                                                                    .toString(),
                                                                fontSize = 17.sp,
                                                                color =
                                                                    if (selected) {
                                                                        Color.White
                                                                    } else if (
                                                                        date.month ==
                                                                        month.month
                                                                    ) {
                                                                        VehicleInk
                                                                    } else {
                                                                        Color(
                                                                            0xFFA8AFBA
                                                                        )
                                                                    }
                                                            )

                                                            Box(
                                                                Modifier
                                                                    .size(4.dp)
                                                                    .background(
                                                                        if (date in dots) {
                                                                            if (selected) {
                                                                                Color.White
                                                                            } else {
                                                                                Color(
                                                                                    0xFF285B9D
                                                                                )
                                                                            }
                                                                        } else {
                                                                            Color.Transparent
                                                                        },
                                                                        CircleShape
                                                                    )
                                                            )
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                }
                            }
                        }
                    }
                }
            }
        }

        BookingFilterSheet(model)
        BookingEditor(model)
    }
}

@Composable
internal fun BookingToolbar(
    model: BookingViewModel,
    onToday: () -> Unit
) {
    val today = LocalDate.now(
        ZoneId.of("Asia/Jerusalem")
    )

    Row(
        modifier = Modifier
            .widthIn(max = 340.dp)
            .fillMaxWidth()
            .background(
                Color(0xFFEDF0F3),
                RoundedCornerShape(40.dp)
            )
            .padding(6.dp),
        horizontalArrangement = Arrangement.SpaceEvenly,
        verticalAlignment = Alignment.CenterVertically
    ) {
        BookingToolbarIcon(
            asset = R.drawable.ic_filter,
            label = "סינון",
            onClick = model::openFilters
        )

        BookingToolbarIcon(
            asset = R.drawable.ic_edit,
            label = "עריכה",
            onClick = {
                model.selectMode(
                    BookingSelection.EDIT
                )
            }
        )

        BookingToolbarIcon(
            asset = R.drawable.trash_icon,
            label = "ביטול הזמנה",
            iconSize = 40.dp,
            onClick = {
                model.selectMode(
                    BookingSelection.CANCEL
                )
            }
        )

        BookingToolbarIcon(
            asset = R.drawable.ic_add,
            label = "הוספה",
            onClick = model::openCreate
        )

        Box(
            modifier = Modifier
                .size(48.dp)
                .background(
                    Color.White.copy(alpha = .8f),
                    CircleShape
                )
                .clickable(onClick = onToday),
            contentAlignment = Alignment.Center
        ) {
            Text(
                text = today.dayOfMonth.toString(),
                color = VehicleInk,
                fontSize = 16.sp,
                fontWeight = FontWeight.Bold,
                textAlign = TextAlign.Center
            )
        }
    }
}

@Composable
internal fun BookingReservationRow(
    row: BookingReservation,
    select: (() -> Unit)? = null
) {
    Row(
        Modifier
            .fillMaxWidth()
            .background(
                Color.White.copy(alpha = .72f),
                RoundedCornerShape(18.dp)
            )
            .border(
                1.dp,
                if (select == null) VehicleBorder else VehicleInk,
                RoundedCornerShape(18.dp)
            )
            .then(
                if (select != null) {
                    Modifier.clickable(onClick = select)
                } else {
                    Modifier
                }
            )
            .padding(12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Column(
            Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            Text(
                row.ownerName,
                color = VehicleInk,
                fontWeight = FontWeight.SemiBold,
                fontSize = 17.sp
            )

            Text(
                if (row.vehicleRef == null) {
                    "הזמנה כללית"
                } else {
                    row.vehicleName.orEmpty()
                },
                color = Color(0xFF738197),
                fontSize = 14.sp
            )

            CompositionLocalProvider(
                LocalLayoutDirection provides LayoutDirection.Ltr
            ) {
                Text(
                    bookingTimeLabel(row),
                    color = VehicleInk,
                    fontSize = 13.sp
                )
            }
        }

        val colors = listOf(
            Color(0xFFE7EFFC),
            Color(0xFFE8E8FC),
            Color(0xFFF8E4F3),
            Color(0xFFE2F1E8)
        )

        Box(
            Modifier
                .size(36.dp)
                .background(
                    colors[
                        Math.floorMod(
                            row.ownerName.hashCode(),
                            colors.size
                        )
                    ],
                    CircleShape
                ),
            contentAlignment = Alignment.Center
        ) {
            Text(
                historyInitials(row.ownerName),
                color = VehicleInk,
                fontSize = 13.sp,
                fontWeight = FontWeight.Medium
            )
        }

        Image(
            painter = painterResource(
                vehicleIllustration(row.category)
            ),
            contentDescription = null,
            modifier = Modifier
                .width(72.dp)
                .height(46.dp),
            contentScale = ContentScale.Fit
        )
    }
}

@Composable
private fun BookingToolbarIcon(
    asset: Int,
    label: String,
    iconSize: Dp = 24.dp,
    onClick: (() -> Unit)? = null
) {
    Box(
        modifier = Modifier
            .size(48.dp)
            .background(
                Color.White.copy(alpha = .8f),
                CircleShape
            )
            .then(
                if (onClick != null) {
                    Modifier.clickable(onClick = onClick)
                } else {
                    Modifier
                }
            ),
        contentAlignment = Alignment.Center
    ) {
        Image(
            painter = painterResource(asset),
            contentDescription = label,
            modifier = Modifier.size(iconSize)
        )
    }
}

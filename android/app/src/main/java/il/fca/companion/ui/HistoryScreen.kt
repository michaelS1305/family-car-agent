package il.fca.companion.ui

import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.AbsoluteAlignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.unit.Dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import il.fca.companion.R
import il.fca.companion.net.*
import java.time.*
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlinx.coroutines.flow.distinctUntilChanged

private val HistoryInk = Color(0xFF23364E)
private val HistorySecondary = Color(0xFF788699)
private val HistoryOutline = Color(0xFFE3E7EC)

internal const val HISTORY_ILLUSTRATION_SLOT_DP = 40

internal fun historyInitials(name: String): String {
    val first = name.trim().split(Regex("\\s+"), limit = 2).firstOrNull().orEmpty()
    return first.codePoints().limit(2).toArray().let { String(it, 0, it.size) }
}

internal fun historyNearEnd(
    lastKey: Any?,
    rows: List<HistoryUsage>
): Boolean =
    rows.isNotEmpty() && rows.takeLast(3).any { it.sessionRef == lastKey }

@Composable
internal fun HistoryScreen(
    model: HistoryViewModel,
    familyId: Long?,
    back: () -> Unit
) {
    val lifecycle = LocalLifecycleOwner.current.lifecycle

    DisposableEffect(model, familyId, lifecycle) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> model.start()
                Lifecycle.Event.ON_STOP -> model.stop()
                else -> Unit
            }
        }

        lifecycle.addObserver(observer)

        if (lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) {
            model.start()
        }

        onDispose {
            lifecycle.removeObserver(observer)
            model.stop()
        }
    }

    val state = model.state
    val list = rememberLazyListState()
    val zone = remember { ZoneId.systemDefault() }

    LaunchedEffect(list, model) {
        snapshotFlow {
            val current = model.state
            val keys = list.layoutInfo.visibleItemsInfo.map { it.key }

            Triple(
                current.rows.lastOrNull()?.sessionRef,
                current.loading,
                keys.any { historyNearEnd(it, current.rows) }
            )
        }.distinctUntilChanged().collect { (_, loading, near) ->
            if (near && !loading) {
                model.nextPage()
            }
        }
    }

    LaunchedEffect(state.applied) {
        list.scrollToItem(0)
    }

    Box(
        Modifier
            .fillMaxSize()
            .background(Color(0xFFF6F7F7)),
        contentAlignment = Alignment.TopCenter
    ) {
        LazyColumn(
            state = list,
            modifier = Modifier
                .widthIn(max = 620.dp)
                .fillMaxSize()
                .navigationBarsPadding(),
            contentPadding = PaddingValues(
                horizontal = 16.dp,
                vertical = 12.dp
            ),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            item(key = "header") {
                Box(
                    Modifier
                        .fillMaxWidth()
                        .height(76.dp)
                ) {
                    Image(
                        painterResource(R.drawable.fca_header_wordmark),
                        "Family Car Agent",
                        Modifier
                            .align(Alignment.Center)
                            .fillMaxWidth(0.68f)
                            .height(70.dp)
                            .graphicsLayer {
                                compositingStrategy = CompositingStrategy.Offscreen
                                blendMode = BlendMode.Multiply
                            },
                        contentScale = ContentScale.Fit
                    )

                    HistoryBack(back)
                }
            }

            item(key = "title") {
                Box(
                    Modifier
                        .fillMaxWidth()
                        .height(108.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Image(
                        painterResource(R.drawable.history_icon),
                        "היסטוריה",
                        Modifier
                            .requiredSize(200.dp)
                            .offset(y = (-15).dp),
                        contentScale = ContentScale.Fit
                    )
                }
            }

            item(key = "current") {
                CurrentCapsule(
                    state.current,
                    zone,
                    model::retryCurrent
                )
            }

            item(key = "filters") {
                Surface(
                    onClick = model::openFilters,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(28.dp),
                    color = Color.White.copy(alpha = 0.88f),
                    border = BorderStroke(1.dp, HistoryOutline)
                ) {
                    Row(
                        Modifier.padding(
                            horizontal = 18.dp,
                            vertical = 13.dp
                        ),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        Text(
                            "›",
                            fontSize = 24.sp,
                            color = HistoryInk
                        )

                        Text(
                            if (state.applied.empty) "הכול" else "סינון פעיל",
                            Modifier.weight(1f),
                            color = HistorySecondary
                        )

                        Text(
                            "סינון",
                            fontWeight = FontWeight.SemiBold,
                            color = HistoryInk
                        )

                        Image(
                            painterResource(R.drawable.ic_filter),
                            null,
                            Modifier.size(24.dp)
                        )
                    }
                }
            }

            item(key = "heading") {
                Text(
                    "שימושים אחרונים",
                    Modifier
                        .fillMaxWidth()
                        .padding(
                            top = 8.dp,
                            bottom = 2.dp
                        ),
                    color = HistorySecondary,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 17.sp
                )
            }

            items(
                state.rows,
                key = { it.sessionRef }
            ) {
                UsageRow(it, zone)
            }

            item(key = "footer") {
                Column(
                    Modifier
                        .fillMaxWidth()
                        .padding(12.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    when {
                        state.loading -> {
                            Text(
                                "טוען שימושים…",
                                color = HistorySecondary
                            )
                        }

                        state.pageError -> {
                            Text(
                                "לא ניתן לטעון את ההיסטוריה כרגע",
                                color = HistorySecondary
                            )

                            TextButton(
                                onClick = model::retryPage
                            ) {
                                Text("נסה שוב")
                            }
                        }

                        state.loaded && state.rows.isEmpty() -> {
                            Text(
                                "לא נמצאו שימושים",
                                color = HistorySecondary
                            )
                        }
                    }
                }
            }
        }
    }

    if (state.sheet) {
        HistoryFilterSheet(
            state,
            model,
            zone
        )
    }
}

@Composable
private fun HistoryBack(
    back: () -> Unit
) {
    Box(
        Modifier.fillMaxWidth()
    ) {
        IconButton(
            onClick = back,
            modifier = Modifier
                .align(AbsoluteAlignment.TopRight)
                .size(48.dp)
                .background(
                    Color.White,
                    CircleShape
                )
        ) {
            Icon(
                painterResource(R.drawable.ic_chevron_back),
                "חזרה",
                tint = HistoryInk,
                modifier = Modifier.size(24.dp)
            )
        }
    }
}

@Composable
private fun HistoryCard(
    tint: Color = Color.White.copy(alpha = 0.88f),
    content: @Composable () -> Unit
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(22.dp),
        color = tint,
        border = BorderStroke(
            1.dp,
            HistoryOutline
        ),
        shadowElevation = 1.dp,
        content = content
    )
}

@Composable
private fun CurrentCapsule(
    current: CurrentVehicleState,
    zone: ZoneId,
    retry: () -> Unit
) {
    HistoryCard(
        if (current.allAvailable) {
            Color(0xFFF1FAF5)
        } else {
            Color.White.copy(alpha = 0.88f)
        }
    ) {
        Column(
            Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            when {
                current.status == CurrentUseStatus.LOADING -> {
                    Text(
                        "טוען מצב רכבים…",
                        color = HistorySecondary
                    )
                }

                current.status == CurrentUseStatus.UNAVAILABLE -> {
                    Text(
                        "מצב הרכבים אינו זמין כרגע",
                        color = HistorySecondary
                    )

                    TextButton(
                        onClick = retry
                    ) {
                        Text("נסה שוב")
                    }
                }

                current.allAvailable -> {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        Box(
                            Modifier
                                .size(10.dp)
                                .background(
                                    Color(0xFF279759),
                                    CircleShape
                                )
                        )

                        Column {
                            Text(
                                "כל הרכבים פנויים",
                                color = Color(0xFF315D65),
                                fontWeight = FontWeight.SemiBold
                            )

                            Text(
                                "אין רכבים בשימוש כרגע",
                                color = HistorySecondary,
                                fontSize = 13.sp
                            )
                        }
                    }
                }

                else -> {
                    current.occupied.forEach { vehicle ->
                        Row(
                            Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            IllustrationSlot()

                            InitialsAvatar(
                                vehicle.driver.orEmpty()
                            )

                            Column(
                                Modifier.weight(1f)
                            ) {
                                Text(
                                    "${vehicle.name} — ${vehicle.driver.orEmpty()}",
                                    color = HistoryInk,
                                    fontWeight = FontWeight.SemiBold,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis
                                )

                                Text(
                                    "בשימוש מ־${clock(checkNotNull(vehicle.startedAt), zone)}",
                                    color = HistorySecondary,
                                    fontSize = 13.sp
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun IllustrationSlot() {
    Spacer(
        Modifier.size(
            HISTORY_ILLUSTRATION_SLOT_DP.dp
        )
    )
}

@Composable
private fun InitialsAvatar(
    name: String
) {
    val colors = listOf(
        Color(0xFFE7EFFC),
        Color(0xFFE8E8FC),
        Color(0xFFF8E4F3),
        Color(0xFFE2F1E8)
    )

    Box(
        Modifier
            .size(30.dp)
            .background(
                colors[Math.floorMod(name.hashCode(), colors.size)],
                CircleShape
            ),
        contentAlignment = Alignment.Center
    ) {
        Text(
            historyInitials(name),
            fontSize = 12.sp,
            color = HistoryInk,
            fontWeight = FontWeight.Medium
        )
    }
}

private fun clock(
    value: Instant,
    zone: ZoneId
): String =
    DateTimeFormatter
        .ofPattern("HH:mm")
        .withZone(zone)
        .format(value)

@Composable
private fun UsageRow(
    row: HistoryUsage,
    zone: ZoneId
) {
    HistoryCard {
        CompositionLocalProvider(
            LocalLayoutDirection provides LayoutDirection.Ltr
        ) {
            Row(
                Modifier
                    .fillMaxWidth()
                    .heightIn(min = 76.dp)
                    .padding(
                        horizontal = 10.dp,
                        vertical = 12.dp
                    ),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                Text(
                    "${clock(row.startedAt, zone)}–${clock(row.endedAt, zone)}",
                    fontSize = 12.sp,
                    color = HistorySecondary,
                    maxLines = 1
                )

                CompositionLocalProvider(
                    LocalLayoutDirection provides LayoutDirection.Rtl
                ) {
                    Column(
                        Modifier.weight(1f),
                        horizontalAlignment = Alignment.End
                    ) {
                        Text(
                            "${row.vehicleName} — ${row.name}",
                            Modifier.fillMaxWidth(),
                            color = HistoryInk,
                            fontWeight = FontWeight.SemiBold,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            textAlign = TextAlign.Right
                        )

                        Text(
                            DateTimeFormatter
                                .ofPattern(
                                    "d MMMM yyyy",
                                    Locale.forLanguageTag("he")
                                )
                                .withZone(zone)
                                .format(row.startedAt),
                            Modifier.fillMaxWidth(),
                            fontSize = 12.sp,
                            color = HistorySecondary,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            textAlign = TextAlign.Right
                        )
                    }
                }

                InitialsAvatar(row.name)
                IllustrationSlot()
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun HistoryFilterSheet(
    state: HistoryState,
    model: HistoryViewModel,
    zone: ZoneId
) {
    var boundary by remember {
        mutableStateOf<Boolean?>(null)
    }

    ModalBottomSheet(
        onDismissRequest = model::dismissFilters,
        containerColor = Color(0xFFFAFBFC)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(
                    start = 20.dp,
                    end = 20.dp,
                    top = 0.dp,
                    bottom = 4.dp
                ),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(34.dp),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    "סינון היסטוריה",
                    color = HistoryInk,
                    fontSize = 21.sp,
                    fontWeight = FontWeight.Bold
                )
            }

            FilterChoice(
                label = "רכב",
                asset = R.drawable.car,
                value = state.draft.vehicleRef,
                choices = state.vehicleOptions.map {
                    it.ref to it.name
                }
            ) {
                model.editDraft(
                    state.draft.copy(
                        vehicleRef = it
                    )
                )
            }

            FilterChoice(
                label = "משתמש",
                asset = R.drawable.user,
                value = state.draft.memberRef,
                choices = state.members.map {
                    it.ref to it.name
                },
                labelWidth = 86.dp
            ) {
                model.editDraft(
                    state.draft.copy(
                        memberRef = it
                    )
                )
            }

            if (state.optionsLoading) {
                Text(
                    "טוען משתמשים…",
                    color = HistorySecondary,
                    fontSize = 13.sp
                )
            }

            if (state.optionsError) {
                TextButton(
                    onClick = model::loadOptions
                ) {
                    Text(
                        "לא ניתן לטעון משתמשים — נסה שוב",
                        fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold
                    )
                }
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Box(
                    modifier = Modifier.size(26.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Image(
                        painter = painterResource(R.drawable.ic_calender),
                        contentDescription = null,
                        modifier = Modifier.size(24.dp)
                    )
                }

                Spacer(Modifier.width(8.dp))

                Text(
                    text = "זמן",
                    modifier = Modifier.width(74.dp),
                    color = HistoryInk,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 16.sp,
                    maxLines = 1
                )

                Spacer(Modifier.weight(1f))

                Row(
                    modifier = Modifier.width(176.dp),
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    val fromValue = state.draft.from
                    val toValue = state.draft.to

                    OutlinedButton(
                        onClick = {
                            boundary = true
                        },
                        modifier = Modifier
                            .weight(1f)
                            .height(40.dp),
                        contentPadding = PaddingValues(
                            horizontal = 3.dp,
                            vertical = 0.dp
                        )
                    ) {
                        Text(
                            text = fromValue
                                ?.atZoneSameInstant(zone)
                                ?.format(
                                    DateTimeFormatter.ofPattern(
                                        "dd/MM HH:mm"
                                    )
                                )
                                ?.let {
                                    "מ־ $it"
                                }
                                ?: "מ־",
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            fontSize = 12.sp
                        )
                    }

                    OutlinedButton(
                        onClick = {
                            boundary = false
                        },
                        modifier = Modifier
                            .weight(1f)
                            .height(40.dp),
                        contentPadding = PaddingValues(
                            horizontal = 3.dp,
                            vertical = 0.dp
                        )
                    ) {
                        Text(
                            text = toValue
                                ?.atZoneSameInstant(zone)
                                ?.format(
                                    DateTimeFormatter.ofPattern(
                                        "dd/MM HH:mm"
                                    )
                                )
                                ?.let {
                                    "עד $it"
                                }
                                ?: "עד",
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            fontSize = 12.sp
                        )
                    }
                }
            }

            if (state.rangeError) {
                Text(
                    "זמן ההתחלה חייב להיות לפני זמן הסיום או זהה לו",
                    color = MaterialTheme.colorScheme.error,
                    fontSize = 13.sp
                )
            }

            Button(
                onClick = model::applyFilters,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(44.dp),
                shape = RoundedCornerShape(22.dp)
            ) {
                Text(
                    "הצג תוצאות",
                    fontSize = 16.sp,
                    fontWeight = FontWeight.Bold
                )
            }

            OutlinedButton(
                onClick = model::clearFilters,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(42.dp)
            ) {
                Text(
                    "נקה סינון",
                    fontSize = 16.sp,
                    fontWeight = FontWeight.Bold
                )
            }

            if (state.current.status != CurrentUseStatus.READY) {
                TextButton(
                    onClick = model::retryCurrent,
                    modifier = Modifier
                        .align(Alignment.CenterHorizontally)
                        .height(28.dp)
                        .offset(y = (-4).dp),
                    contentPadding = PaddingValues(
                        horizontal = 8.dp,
                        vertical = 0.dp
                    )
                ) {
                    Text(
                        "רענון רשימת רכבים",
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Bold
                    )
                }
            }

            Spacer(
                Modifier.height(2.dp)
            )
        }
    }

    boundary?.let { from ->
        HistoryDateTimePicker(
            initial = if (from) {
                state.draft.from
            } else {
                state.draft.to
            },
            zone = zone,
            dismiss = {
                boundary = null
            },
            selected = { value ->
                model.editDraft(
                    if (from) {
                        state.draft.copy(
                            from = value
                        )
                    } else {
                        state.draft.copy(
                            to = value
                        )
                    }
                )

                boundary = null
            }
        )
    }
}

@Composable
private fun FilterChoice(
    label: String,
    asset: Int,
    value: String?,
    choices: List<Pair<String, String>>,
    labelWidth: Dp = 74.dp,
    selected: (String?) -> Unit
) {
    var expanded by remember {
        mutableStateOf(false)
    }

    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(
            modifier = Modifier.size(26.dp),
            contentAlignment = Alignment.Center
        ) {
            Image(
                painter = painterResource(asset),
                contentDescription = null,
                modifier = Modifier
                    .requiredSize(58.dp)
                    .offset(y = (-2).dp),
                contentScale = ContentScale.Fit
            )
        }

        Spacer(Modifier.width(8.dp))

        Text(
            text = label,
            modifier = Modifier.width(labelWidth),
            color = HistoryInk,
            fontWeight = FontWeight.SemiBold,
            fontSize = 16.sp,
            maxLines = 1,
            softWrap = false,
            overflow = TextOverflow.Visible
        )

        Spacer(Modifier.weight(1f))

        Box(
            modifier = Modifier.width(176.dp)
        ) {
            OutlinedButton(
                onClick = {
                    expanded = true
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(40.dp),
                contentPadding = PaddingValues(
                    horizontal = 8.dp,
                    vertical = 0.dp
                )
            ) {
                Text(
                    text = if (value == null) {
                        "הכול"
                    } else {
                        choices
                            .find {
                                it.first == value
                            }
                            ?.second
                            ?: "נבחר"
                    },
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    fontSize = 14.sp
                )
            }

            DropdownMenu(
                expanded = expanded,
                onDismissRequest = {
                    expanded = false
                }
            ) {
                DropdownMenuItem(
                    text = {
                        Text("הכול")
                    },
                    onClick = {
                        selected(null)
                        expanded = false
                    }
                )

                choices.forEach { (ref, name) ->
                    DropdownMenuItem(
                        text = {
                            Text(name)
                        },
                        onClick = {
                            selected(ref)
                            expanded = false
                        }
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun HistoryDateTimePicker(
    initial: OffsetDateTime?,
    zone: ZoneId,
    dismiss: () -> Unit,
    selected: (OffsetDateTime) -> Unit
) {
    val start = remember {
        initial?.atZoneSameInstant(zone)
            ?: ZonedDateTime.now(zone)
    }

    val date = rememberDatePickerState(
        initialSelectedDateMillis = start
            .toLocalDate()
            .atStartOfDay(ZoneOffset.UTC)
            .toInstant()
            .toEpochMilli()
    )

    val time = rememberTimePickerState(
        start.hour,
        start.minute,
        is24Hour = true
    )

    var choosingTime by remember {
        mutableStateOf(false)
    }

    if (!choosingTime) {
        DatePickerDialog(
            onDismissRequest = dismiss,
            confirmButton = {
                TextButton(
                    enabled = date.selectedDateMillis != null,
                    onClick = {
                        choosingTime = true
                    }
                ) {
                    Text("המשך")
                }
            },
            dismissButton = {
                TextButton(
                    onClick = dismiss
                ) {
                    Text("ביטול")
                }
            }
        ) {
            DatePicker(date)
        }
    } else {
        AlertDialog(
            onDismissRequest = dismiss,
            title = {
                Text("בחירת שעה")
            },
            text = {
                TimeInput(time)
            },
            dismissButton = {
                TextButton(
                    onClick = dismiss
                ) {
                    Text("ביטול")
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        val day = Instant
                            .ofEpochMilli(
                                checkNotNull(
                                    date.selectedDateMillis
                                )
                            )
                            .atZone(ZoneOffset.UTC)
                            .toLocalDate()

                        selected(
                            day
                                .atTime(
                                    time.hour,
                                    time.minute
                                )
                                .atZone(zone)
                                .toOffsetDateTime()
                        )
                    }
                ) {
                    Text("אישור")
                }
            }
        )
    }
}
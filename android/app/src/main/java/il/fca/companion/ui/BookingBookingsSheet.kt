
package il.fca.companion.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import il.fca.companion.net.BookingReservation

@Composable
internal fun BookingBookingsSheet(
    model: BookingViewModel,
    rows: List<BookingReservation>,
    loaded: Boolean,
    modifier: Modifier = Modifier,
    onToday: () -> Unit
) {
    val action = model.visibleAction
    val data = model.visibleData
    val selecting = action.selection != BookingSelection.NONE

    Column(
        modifier
            .fillMaxWidth()
            .padding(horizontal = 18.dp)
    ) {
        // Drag handle remains visible in PEEK.
        Box(
            Modifier
                .fillMaxWidth()
                .clickable {
                    model.expandSheet(!model.sheetExpanded)
                }
                .padding(top = 9.dp, bottom = 8.dp),
            contentAlignment = Alignment.Center
        ) {
            Box(
                Modifier
                    .width(38.dp)
                    .height(4.dp)
                    .background(
                        Color(0xFFBFC7D0),
                        RoundedCornerShape(4.dp)
                    )
            )
        }

        // Toolbar is now inside the persistent sheet.
        Box(
            modifier = Modifier.fillMaxWidth(),
            contentAlignment = Alignment.Center
        ) {
            BookingToolbar(
                model = model,
                onToday = onToday
            )
        }

        // Selected date and sheet state.
        Column(
            Modifier
                .fillMaxWidth()
                .clickable {
                    model.expandSheet(!model.sheetExpanded)
                }
                .padding(top = 8.dp, bottom = 8.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            if (selecting) {
                Text(
                    if (action.selection == BookingSelection.EDIT)
                        "בחירת הזמנה לעריכה"
                    else
                        "בחירת הזמנה לביטול",
                    color = VehicleInk,
                    fontWeight = FontWeight.Bold
                )
            }

            Text(
                bookingDateLabel(model.selectedDate),
                color = VehicleInk,
                fontWeight = FontWeight.SemiBold,
                fontSize = 15.sp
            )

            Text(
                if (loaded && !data.error) {
                    "${rows.size} הזמנות · ${
                        if (model.sheetExpanded)
                            "הקישו לצמצום"
                        else
                            "החליקו למעלה להצגה"
                    }"
                } else if (data.error) {
                    "טעינת ההזמנות לא הושלמה"
                } else {
                    "טוען הזמנות…"
                },
                color = Color(0xFF738197),
                fontSize = 12.sp
            )
        }

        LazyColumn(
            Modifier
                .weight(1f)
                .fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(10.dp),
            contentPadding = PaddingValues(bottom = 16.dp)
        ) {
            if (selecting) {
                item {
                    TextButton(
                        onClick = { model.dismiss() }
                    ) {
                        Text("יציאה מבחירה")
                    }

                    if (
                        loaded &&
                        !data.error &&
                        rows.none(model::eligible)
                    ) {
                        Text(
                            "אין הזמנות זמינות לבחירה בתאריך זה.",
                            color = VehicleInk
                        )
                    }
                }
            }

            action.notice?.let { notice ->
                item {
                    Text(
                        notice,
                        color = VehicleInk,
                        fontSize = 14.sp
                    )
                }
            }

            if (
                model.visiblePending != null &&
                !action.submitting
            ) {
                item {
                    Text(
                        "תוצאת הפעולה אינה ודאית. ניסיון נוסף עלול לבצע אותה שוב.",
                        color = VehicleInk
                    )

                    if (!model.canAcknowledge) {
                        Text(
                            "יש לרענן טווח ומסננים המכסים את הפעולה לפני אישור המשך.",
                            color = VehicleInk
                        )

                        model.visiblePending?.let { pending ->
                            Text(
                                "תאריך לבדיקה: ${
                                    bookingDateLabel(
                                        pending.start.toLocalDate()
                                    )
                                }",
                                color = VehicleInk,
                                fontSize = 13.sp
                            )

                            pending.original
                                ?.takeIf {
                                    it.start.toLocalDate() !=
                                            pending.start.toLocalDate()
                                }
                                ?.let {
                                    Text(
                                        "יש לבדוק גם את התאריך המקורי: ${
                                            bookingDateLabel(
                                                it.start.toLocalDate()
                                            )
                                        }",
                                        color = VehicleInk,
                                        fontSize = 13.sp
                                    )
                                }
                        }
                    }

                    TextButton(
                        onClick = model::retry
                    ) {
                        Text("רענון ובדיקת ההזמנות")
                    }

                    if (model.canAcknowledge) {
                        OutlinedButton(
                            onClick = model::acknowledgeUncertain
                        ) {
                            Text(
                                "בדקתי את ההזמנות, המשך למרות אי־הוודאות"
                            )
                        }
                    }
                }
            }

            if (data.loading || data.refreshing) {
                item {
                    CircularProgressIndicator(
                        Modifier.size(24.dp),
                        strokeWidth = 2.dp
                    )
                }
            }

            if (data.error) {
                item {
                    Text(
                        if (loaded)
                            "לא ניתן לרענן את ההזמנות"
                        else
                            "לא ניתן לטעון את ההזמנות",
                        color = VehicleInk
                    )

                    TextButton(
                        onClick = model::retry
                    ) {
                        Text("נסה שוב")
                    }
                }
            }

            if (loaded) {
                if (rows.isEmpty() && !data.error) {
                    item {
                        Text(
                            if (model.query.effective == null)
                                "טווח הסינון אינו חופף ללוח המוצג."
                            else
                                "אין הזמנות לתאריך זה תחת המסננים הנוכחיים.",
                            color = VehicleInk
                        )
                    }
                }

                items(
                    rows,
                    key = { it.ref }
                ) { row ->
                    BookingReservationRow(
                        row,
                        if (
                            selecting &&
                            model.eligible(row) &&
                            model.visiblePending == null
                        ) {
                            { model.choose(row.ref) }
                        } else {
                            null
                        }
                    )
                }
            }
        }
    }
}

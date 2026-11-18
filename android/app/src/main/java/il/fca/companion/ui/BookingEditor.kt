package il.fca.companion.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.time.Instant
import java.time.LocalTime
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun BookingEditor(model: BookingViewModel) {
    val state = model.visibleAction
    val draft = state.draft
    val confirmation = state.confirmation
    if (draft == null && confirmation == null) return
    val idle = !state.submitting && !state.uncertain
    var picker by remember(draft?.original?.ref, confirmation?.ref) { mutableStateOf<String?>(null) }
    val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true,
        confirmValueChange = { it != SheetValue.Hidden || !model.visibleAction.submitting })
    ModalBottomSheet(onDismissRequest = { model.dismiss() }, sheetState = sheet,
        properties = ModalBottomSheetProperties(shouldDismissOnBackPress = !state.submitting),
        containerColor = fcaColor(Color(0xFFF9FAFA), FcaColorRole.SURFACE)) {
        BackHandler { model.dismiss() }
        Column(Modifier.fillMaxWidth().imePadding().verticalScroll(rememberScrollState()).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text(if (confirmation != null) "האם לבטל את ההזמנה?" else if (draft?.original == null) "הוספת הזמנה" else "עריכת הזמנה",
                fontSize = 23.sp, fontWeight = FontWeight.Bold, color = VehicleInk)
            if (draft != null) {
                val dateFormat = DateTimeFormatter.ofPattern("dd/MM/yyyy")
                val timeFormat = DateTimeFormatter.ofPattern("HH:mm")
                BookingInput("תאריך התחלה", draft.startDate.format(dateFormat), idle && !model.startLocked()) { picker = "startDate" }
                BookingInput("שעת התחלה", draft.startTime?.format(timeFormat) ?: "בחירת שעה", idle && !model.startLocked()) { picker = "startTime" }
                BookingInput("תאריך סיום", draft.endDate.format(dateFormat), idle) { picker = "endDate" }
                BookingInput("שעת סיום", draft.endTime?.format(timeFormat) ?: "בחירת שעה", idle) { picker = "endTime" }
                Text("רכב", color = VehicleInk, fontWeight = FontWeight.SemiBold)
                if (state.vehiclesLoading) CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp)
                if (state.vehicleError) {
                    Text("לא ניתן לטעון את הרכבים", color = MaterialTheme.colorScheme.error)
                    TextButton(onClick = model::loadVehicles, enabled = idle && !state.vehiclesLoading) { Text("נסה שוב") }
                }
                if (state.vehiclesLoaded) {
                    val choices = state.vehicles.filterNot { it.readOnly }
                    var expanded by remember { mutableStateOf(false) }
                    val original = draft.original
                    val label = if (draft.vehicleRef == null) {
                        if (original != null || choices.isEmpty()) "הזמנה כללית" else "בחירת רכב"
                    } else state.vehicles.find { it.ref == draft.vehicleRef }?.let {
                        it.name + if (it.readOnly) " (לא פעיל)" else ""
                    } ?: original?.vehicleName ?: "הרכב המקושר להזמנה"
                    Box {
                        OutlinedButton(onClick = { expanded = true }, modifier = Modifier.fillMaxWidth(),
                            enabled = idle && !state.vehiclesLoading && !state.vehicleError &&
                                (choices.isNotEmpty() || original != null)) { Text(label) }
                        DropdownMenu(expanded, { expanded = false }) {
                            if (original != null && choices.none { it.ref == original.vehicleRef }) {
                                DropdownMenuItem(text = { Text(if (original.vehicleRef == null) "הזמנה כללית"
                                    else (original.vehicleName ?: "הרכב המקושר") + " — שימור השיוך") },
                                    onClick = { model.chooseVehicle(original.vehicleRef); expanded = false })
                            }
                            choices.forEach { vehicle -> DropdownMenuItem(text = { Text(vehicle.name) },
                                onClick = { model.chooseVehicle(vehicle.ref); expanded = false }) }
                        }
                    }
                }
            }
            if (confirmation != null) {
                Text(if (confirmation.vehicleRef == null) "הזמנה כללית" else confirmation.vehicleName ?: "הרכב המקושר להזמנה", color = VehicleInk)
                Text(bookingDateLabel(confirmation.start.toLocalDate()), color = VehicleInk)
                Text(bookingTimeLabel(confirmation), color = VehicleInk)
            }
            state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            if (state.uncertain) {
                Button(onClick = model::reconcileOutcome, modifier = Modifier.fillMaxWidth()) { Text("רענון ובדיקת ההזמנות") }
            } else {
                Button(onClick = { picker = null; model.submit() }, modifier = Modifier.fillMaxWidth(),
                    enabled = idle && (draft == null || (state.vehiclesLoaded && !state.vehiclesLoading && !state.vehicleError &&
                        draft.startTime != null && draft.endTime != null)),
                    colors = ButtonDefaults.buttonColors(containerColor = VehicleInk)) {
                    Text(if (state.submitting) "ממתינים לאישור…" else if (confirmation != null) "ביטול הזמנה" else "שמירה")
                }
            }
            TextButton(onClick = { model.dismiss() }, enabled = !state.submitting, modifier = Modifier.fillMaxWidth()) { Text("חזרה") }
        }
    }
    if (picker != null && draft != null && idle) key(picker) {
        val field = checkNotNull(picker)
        val start = field.startsWith("start")
        if (field.endsWith("Date")) {
            val date = if (start) draft.startDate else draft.endDate
            val dateState = rememberDatePickerState(initialSelectedDateMillis = date.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli())
            DatePickerDialog(onDismissRequest = { picker = null },
                confirmButton = { TextButton(enabled = dateState.selectedDateMillis != null, onClick = {
                    // Material's UTC millis encode a calendar date, not a booking instant.
                    model.editDate(start, Instant.ofEpochMilli(checkNotNull(dateState.selectedDateMillis)).atZone(ZoneOffset.UTC).toLocalDate())
                    picker = null
                }) { Text("אישור") } }, dismissButton = { TextButton(onClick = { picker = null }) { Text("חזרה") } }) { DatePicker(dateState) }
        } else {
            val value = (if (start) draft.startTime else draft.endTime) ?: LocalTime.NOON
            val time = rememberTimePickerState(value.hour, value.minute, is24Hour = true)
            AlertDialog(onDismissRequest = { picker = null }, title = { Text("בחירת שעה") }, text = { TimeInput(time) },
                confirmButton = { TextButton(onClick = { model.editTime(start, LocalTime.of(time.hour, time.minute)); picker = null }) { Text("אישור") } },
                dismissButton = { TextButton(onClick = { picker = null }) { Text("חזרה") } })
        }
    }
}

@Composable
private fun BookingInput(label: String, value: String, enabled: Boolean, open: () -> Unit) {
    Text(label, color = VehicleInk, fontWeight = FontWeight.SemiBold)
    OutlinedButton(onClick = open, enabled = enabled, modifier = Modifier.fillMaxWidth()) { Text(value) }
}

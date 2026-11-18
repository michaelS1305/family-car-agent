package il.fca.companion.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun BookingFilterSheet(model: BookingViewModel) {
    val state = model.visibleFilters
    if (!state.open) return
    val draft = state.draft
    var picker by remember { mutableStateOf<Boolean?>(null) }
    ModalBottomSheet(onDismissRequest = model::dismissFilters,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true), containerColor = fcaColor(Color(0xFFF6F7F7), FcaColorRole.BACKGROUND)) {
        Column(Modifier.fillMaxWidth().imePadding().verticalScroll(rememberScrollState()).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("סינון הזמנות", style = MaterialTheme.typography.titleLarge, color = VehicleInk)
            if (state.loading) CircularProgressIndicator(Modifier.size(24.dp))
            if (state.error) {
                Text("לא ניתן לטעון את אפשרויות הסינון. הבחירה הקיימת נשמרה.")
                TextButton(onClick = model::loadFilterChoices) { Text("נסה שוב") }
            }
            BookingFilterChoice("רכב", draft.vehicleRef,
                state.vehicles.map { it.ref to (it.name + if (it.readOnly) " (לא פעיל)" else "") },
                "כל הרכבים") { model.editFilters(draft.copy(vehicleRef = it)) }
            BookingFilterChoice("בן משפחה", draft.memberRef, state.members.map { it.ref to it.name },
                "כל בני המשפחה") { model.editFilters(draft.copy(memberRef = it)) }
            val format = DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm")
            listOf(true, false).forEach { start ->
                val value = if (start) draft.start else draft.end
                Row {
                    OutlinedButton(onClick = { picker = start }, modifier = Modifier.weight(1f)) {
                        Text((if (start) "מתאריך: " else "עד תאריך: ") + (value?.format(format) ?: "ללא הגבלה"))
                    }
                    if (value != null) TextButton(onClick = {
                        model.editFilters(if (start) draft.copy(start = null) else draft.copy(end = null))
                    }) { Text("ניקוי") }
                }
            }
            if (state.invalid) Text("זמן ההתחלה חייב להיות לפני זמן הסיום.", color = MaterialTheme.colorScheme.error)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                TextButton(onClick = model::clearDraftFilters) { Text("ניקוי") }
                TextButton(onClick = model::dismissFilters) { Text("ביטול") }
                Button(onClick = model::applyFilters) { Text("הצגת תוצאות") }
            }
        }
    }
    picker?.let { start -> key(start) {
        val initial = (if (start) draft.start else draft.end) ?: model.selectedDate.atStartOfDay()
        BookingFilterDateTime(initial, { picker = null }) { value ->
            model.editFilters(if (start) draft.copy(start = value) else draft.copy(end = value))
            picker = null
        }
    } }
}

@Composable
private fun BookingFilterChoice(label: String, selected: String?, choices: List<Pair<String, String>>,
    all: String, choose: (String?) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Text(label, color = VehicleInk)
    Box {
        OutlinedButton(onClick = { open = true }, modifier = Modifier.fillMaxWidth()) {
            Text(if (selected == null) all else choices.find { it.first == selected }?.second ?: "הבחירה הקיימת אינה זמינה")
        }
        DropdownMenu(open, { open = false }) {
            DropdownMenuItem(text = { Text(all) }, onClick = { choose(null); open = false })
            choices.forEach { (ref, name) -> DropdownMenuItem(text = { Text(name) },
                onClick = { choose(ref); open = false }) }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun BookingFilterDateTime(initial: LocalDateTime, dismiss: () -> Unit, accept: (LocalDateTime) -> Unit) {
    // UTC is only Material DatePicker's date transport, not the Booking timezone.
    val date = rememberDatePickerState(initialSelectedDateMillis = initial.toLocalDate()
        .atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli())
    val time = rememberTimePickerState(initialHour = initial.hour, initialMinute = initial.minute, is24Hour = true)
    var choosingTime by remember { mutableStateOf(false) }
    if (!choosingTime) DatePickerDialog(onDismissRequest = dismiss,
        confirmButton = { TextButton(enabled = date.selectedDateMillis != null, onClick = { choosingTime = true }) { Text("המשך") } },
        dismissButton = { TextButton(onClick = dismiss) { Text("ביטול") } }) { DatePicker(date) }
    else AlertDialog(onDismissRequest = dismiss,
        text = { TimeInput(time) }, confirmButton = { TextButton(onClick = {
            val day = Instant.ofEpochMilli(checkNotNull(date.selectedDateMillis)).atZone(ZoneOffset.UTC).toLocalDate()
            accept(day.atTime(time.hour, time.minute))
        }) { Text("אישור") } }, dismissButton = { TextButton(onClick = dismiss) { Text("ביטול") } })
}

package il.fca.companion.ui

import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import il.fca.companion.R
import il.fca.companion.net.*

@Composable
internal fun AddVehicleScreen(model: VehiclesViewModel) {
    val state = model.state
    val draft = state.draft
    val editable = state.pending == null && !state.submitting
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        VehicleField("שם הרכב", draft.name, "לדוגמה: יונדאי, הרכב של אבא", R.drawable.single_car_icon, editable) {
            model.edit(draft.copy(name = it))
        }
        Text("סוג רכב", color = VehicleInk)
        CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) {
            Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                VehicleCategory.entries.forEach { category ->
                    val selected = draft.category == category
                    Column(Modifier.width(72.dp).height(86.dp).clip(RoundedCornerShape(18.dp))
                        .background(if (selected) Color(0xFFE6EDF4) else Color.White.copy(alpha = .6f))
                        .border(if (selected) 2.dp else 1.dp, if (selected) VehicleInk else VehicleBorder, RoundedCornerShape(18.dp))
                        .selectable(selected, enabled = editable, role = Role.RadioButton) { model.edit(draft.copy(category = category)) }
                        .padding(4.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                        Image(painterResource(vehicleIllustration(category)), null, Modifier.fillMaxWidth().height(44.dp))
                        Text(category.label, color = VehicleInk, fontSize = 11.sp, maxLines = 1)
                    }
                }
            }
        }
        VehicleField("יצרן", draft.manufacturerQuery, "בחרו יצרן", R.drawable.manufacturer_icon, editable,
            model::queryManufacturer)
        when {
            state.catalogLoading -> LinearProgressIndicator(Modifier.fillMaxWidth())
            state.catalogError -> Row(verticalAlignment = Alignment.CenterVertically) {
                Text("לא ניתן לטעון יצרנים", color = VehicleInk)
                TextButton(onClick = model::loadManufacturers) { Text("נסה שוב") }
            }
            state.catalogLoaded && draft.manufacturer == null -> {
                if (state.matchingManufacturers.isEmpty()) Text("לא נמצאו יצרנים", color = Color(0xFF788699))
                else Column(Modifier.fillMaxWidth().heightIn(max = 144.dp).verticalScroll(rememberScrollState())
                    .border(1.dp, VehicleBorder, RoundedCornerShape(16.dp))) {
                    state.matchingManufacturers.forEach { manufacturer ->
                        TextButton(onClick = { model.chooseManufacturer(manufacturer) }, enabled = editable,
                            modifier = Modifier.fillMaxWidth()) { Text(manufacturer.name, Modifier.fillMaxWidth(), color = VehicleInk) }
                    }
                }
            }
        }
        VehicleField("דגם", draft.model, "דגם", R.drawable.single_car_icon, editable) { model.edit(draft.copy(model = it)) }
        VehicleField("מספר רכב", draft.plate, "לדוגמה: 123-45-678", R.drawable.license_plate_icon, editable) {
            model.edit(draft.copy(plate = it))
        }
        state.submitError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        Button(onClick = model::submit, enabled = draft.valid && !state.submitting,
            modifier = Modifier.fillMaxWidth().height(56.dp), shape = RoundedCornerShape(20.dp),
            colors = ButtonDefaults.buttonColors(containerColor = VehicleInk)) {
            if (state.submitting) CircularProgressIndicator(Modifier.size(22.dp), color = Color.White, strokeWidth = 2.dp)
            else Text(if (state.pending != null) "נסה שוב" else "הוספת רכב", fontSize = 20.sp)
        }
        Spacer(Modifier.height(8.dp))
    }
}

@Composable
private fun VehicleField(label: String, value: String, hint: String, icon: Int, enabled: Boolean, change: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(label, color = VehicleInk)
        OutlinedTextField(value, change, enabled = enabled, modifier = Modifier.fillMaxWidth(), singleLine = true,
            placeholder = { Text(hint, fontSize = 14.sp) }, shape = RoundedCornerShape(20.dp),
            leadingIcon = { Image(painterResource(icon), null, Modifier.size(24.dp)) },
            colors = OutlinedTextFieldDefaults.colors(unfocusedBorderColor = VehicleBorder,
                focusedBorderColor = VehicleInk, unfocusedContainerColor = Color.White.copy(alpha = .65f)))
    }
}

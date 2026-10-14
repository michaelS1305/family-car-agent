package il.fca.companion.ui

import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.*
import il.fca.companion.R

internal data class BluetoothChoice(val name: String, val selected: Boolean)

@Composable
internal fun CompanionScreen(name: String, state: CompanionPresentation, busy: Boolean, verified: Boolean,
    retired: Boolean, message: String?, back: () -> Unit, refresh: () -> Unit,
    register: () -> Unit, bluetooth: () -> Unit, permissions: () -> Unit) {
    val actions = verified && !retired && !busy
    CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
        MaterialTheme {
            Column(Modifier.fillMaxSize().background(Color(0xFFF6F7F7)).safeDrawingPadding(), horizontalAlignment = Alignment.CenterHorizontally) {
                VehicleProductHeader(back)
                Column(Modifier.widthIn(max = 620.dp).fillMaxWidth().weight(1f).verticalScroll(rememberScrollState()).padding(18.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("חיבור וזיהוי אוטומטי", fontSize = 24.sp, fontWeight = FontWeight.Bold, color = VehicleInk)
                    Text(name, color = VehicleInk)
                    val health = if (retired) CompanionHealth.RETIRED else state.health
                    val color = when (health) {
                        CompanionHealth.READY -> Color(0xFF148054)
                        CompanionHealth.ACTION -> Color(0xFFAA6217)
                        CompanionHealth.SETUP -> Color(0xFFB64848)
                        else -> Color(0xFF788699)
                    }
                    Row(Modifier.fillMaxWidth().background(color.copy(alpha = .08f), RoundedCornerShape(18.dp))
                        .border(1.dp, color.copy(alpha = .2f), RoundedCornerShape(18.dp)).padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        Image(painterResource(when (health) {
                            CompanionHealth.READY -> R.drawable.success_icon
                            CompanionHealth.SETUP, CompanionHealth.ACTION -> R.drawable.warning_icon
                            else -> R.drawable.info_icon
                        }), null, Modifier.size(32.dp))
                        Text(if (retired) "לא פעיל" else state.overall, Modifier.padding(start = 12.dp), color = color, fontWeight = FontWeight.Bold)
                    }
                    if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
                    message?.let { Text(it, color = VehicleInk) }
                    CompanionCard(R.drawable.phone_icon, "המכשיר הזה", when (state.device) {
                        DeviceHealth.REGISTERED -> "מחובר"
                        DeviceHealth.MISSING -> "לא מחובר"
                        DeviceHealth.INVALID -> "נדרש חיבור מחדש"
                        DeviceHealth.UNKNOWN -> "לא ניתן לאמת כרגע"
                    }, "רישום המכשיר לזיהוי אוטומטי.",
                        if (actions && state.device == DeviceHealth.MISSING) "חיבור המכשיר" else null, register)
                    CompanionCard(R.drawable.bluetooth_icon, "חיבור הרכב", when (state.bluetooth) {
                        CompanionHealth.READY -> state.friendlyName ?: "חיבור נבחר"
                        CompanionHealth.SETUP -> "לא נבחר"
                        CompanionHealth.ACTION -> "נדרשת פעולה בחיבור הרכב"
                        else -> "לא ניתן לאמת כרגע"
                    }, "בחרו חיבור Bluetooth שכבר צומד לטלפון.",
                        if (actions && state.device == DeviceHealth.REGISTERED)
                            if (state.bluetooth == CompanionHealth.READY) "שינוי חיבור" else "בחירת חיבור" else null, bluetooth)
                    CompanionCard(R.drawable.location_icon, "זיהוי אוטומטי", when (state.detection) {
                        CompanionHealth.READY -> "פעיל"
                        CompanionHealth.SETUP -> "נדרשת השלמת הגדרה"
                        else -> "לא ניתן לאמת כרגע"
                    }, "נדרש מיקום מדויק גם ברקע לצורך החזרה ליד הבית. אין מעקב רציף. לאחר שינוי הרשאות יש לרענן.",
                        if (actions) "ניהול הרשאות" else null, permissions)
                    if (!retired) TextButton(refresh, enabled = !busy) { Text("רענון") }
                    if (retired) Text("הגדרות הקישור אינן פעילות לרכב זה", color = VehicleInk)
                }
            }
        }
    }
}

@Composable
private fun CompanionCard(icon: Int, title: String, value: String, note: String, action: String?, click: () -> Unit) {
    VehiclePanel {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Image(painterResource(icon), null, Modifier.size(36.dp))
            Column(Modifier.padding(start = 12.dp)) {
                Text(title, color = VehicleInk, fontWeight = FontWeight.Bold, fontSize = 18.sp)
                Text(value, color = VehicleInk)
            }
        }
        Text(note, color = Color(0xFF788699), fontSize = 13.sp)
        if (action != null) OutlinedButton(click, Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp)) { Text(action) }
    }
}

@Composable
internal fun BluetoothPicker(choices: List<BluetoothChoice>, choose: (Int) -> Unit, close: () -> Unit) {
    CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
        AlertDialog(onDismissRequest = close, title = { Text("בחירת חיבור הרכב") },
            text = {
                Column(Modifier.heightIn(max = 400.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("בחרו את חיבור ה־Bluetooth שאליו הטלפון מתחבר כשהוא ברכב.")
                    choices.forEachIndexed { index, choice ->
                        Row(Modifier.fillMaxWidth().border(1.dp, VehicleBorder, RoundedCornerShape(12.dp))
                            .clickable { choose(index) }.padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                            Image(painterResource(R.drawable.bluetooth_icon), null, Modifier.size(24.dp))
                            Text(choice.name, Modifier.weight(1f).padding(horizontal = 8.dp), color = VehicleInk)
                            RadioButton(choice.selected, { choose(index) })
                        }
                    }
                }
            }, confirmButton = { TextButton(close) { Text("ביטול") } })
    }
}

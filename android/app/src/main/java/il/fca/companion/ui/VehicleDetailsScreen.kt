package il.fca.companion.ui

import android.app.DatePickerDialog
import android.content.Intent
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.AbsoluteAlignment
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.*
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.*
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import il.fca.companion.FcaApplication
import il.fca.companion.MainActivity
import il.fca.companion.R
import il.fca.companion.net.*
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
internal fun VehicleDetailsRoute(ref: String, identity: () -> VehiclesIdentity?, back: () -> Unit) {
    val context = LocalContext.current
    val app = context.applicationContext as FcaApplication
    val currentIdentity by rememberUpdatedState(identity)
    val who = identity()
    val model = remember(ref, who) { VehicleDetailsViewModel(VehicleDetailsApi(app.api), ref, { currentIdentity() }) }
    DisposableEffect(model) { model.start(); onDispose { model.stop() } }
    var revision by remember { mutableIntStateOf(0) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle, model) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) { model.refresh(); revision++ }
        }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer) }
    }
    var companion by remember(ref, who) { mutableStateOf(CompanionPresentation()) }
    LaunchedEffect(ref, who, revision, model.state.detail?.vehicle?.readOnly) {
        companion = CompanionPresentation()
        if (model.state.detail?.vehicle?.readOnly == true) companion = CompanionPresentation(CompanionHealth.RETIRED)
        else if (who != null) {
            val result = withContext(Dispatchers.IO) { readCompanionPresentation(app, who.owner, ref) }
            if (currentIdentity() == who) companion = result
        }
    }
    VehicleDetailsScreen(model, companion, back, openCompanion = {
        if (model.state.detail?.vehicle?.readOnly == false && currentIdentity() == who) {
            context.startActivity(Intent(context, MainActivity::class.java).putExtra(MainActivity.VEHICLE_TARGET, ref))
        }
    }, refreshCompanion = { revision++ })
}

@Composable
internal fun VehicleProductHeader(back: () -> Unit) {
    Box(Modifier.fillMaxWidth().height(76.dp).padding(horizontal = 16.dp)) {
        Image(painterResource(R.drawable.fca_header_wordmark), "Family Car Agent",
            Modifier.align(Alignment.Center).fillMaxWidth(.63f).height(58.dp).graphicsLayer {
                compositingStrategy = CompositingStrategy.Offscreen; blendMode = BlendMode.Multiply
            }, contentScale = ContentScale.Fit)
        IconButton(back, Modifier.align(AbsoluteAlignment.CenterRight).size(46.dp)
            .background(Color.White.copy(alpha = .85f), CircleShape)) {
            Image(painterResource(R.drawable.ic_chevron_back), "חזרה", Modifier.size(22.dp))
        }
    }
}

@Composable
internal fun VehiclePanel(content: @Composable ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxWidth().background(Color.White.copy(alpha = .72f), RoundedCornerShape(18.dp))
        .border(1.dp, VehicleBorder, RoundedCornerShape(18.dp)).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp), content = content)
}

@Composable
internal fun VehicleDetailsScreen(model: VehicleDetailsViewModel, companion: CompanionPresentation,
    back: () -> Unit, openCompanion: () -> Unit, refreshCompanion: () -> Unit) {
    val s = model.state
    BackHandler { if (s.dialog != null) model.close() else back() }
    CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
        Column(Modifier.fillMaxSize().background(Color(0xFFF6F7F7)).navigationBarsPadding(),
            horizontalAlignment = Alignment.CenterHorizontally) {
            VehicleProductHeader(back)
            when {
                s.loading -> CircularProgressIndicator(Modifier.padding(32.dp))
                s.error || s.detail == null -> {
                    Text("לא ניתן לטעון את פרטי הרכב", color = VehicleInk)
                    TextButton(model::refresh) { Text("נסה שוב") }
                }
                else -> {
                    val detail = s.detail
                    val v = detail.vehicle
                    Column(Modifier.widthIn(max = 620.dp).fillMaxWidth().weight(1f)
                        .verticalScroll(rememberScrollState()).padding(horizontal = 18.dp, vertical = 10.dp),
                        verticalArrangement = Arrangement.spacedBy(14.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(v.name, fontSize = 26.sp, color = VehicleInk, fontWeight = FontWeight.Bold)
                        CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) {
                            Image(painterResource(vehicleIllustration(v.category)), null,
                                Modifier.fillMaxWidth(.8f).height(145.dp).alpha(if (v.readOnly) .55f else 1f), contentScale = ContentScale.Fit)
                        }
                        val statusColor = if (v.readOnly) Color(0xFF7A8795) else if (detail.inUse) Color(0xFF9B631A) else Color(0xFF168153)
                        Text(detail.status, Modifier.fillMaxWidth().background(statusColor.copy(alpha = .10f), RoundedCornerShape(16.dp))
                            .padding(10.dp), color = statusColor, fontWeight = FontWeight.Bold, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                        VehiclePanel {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Image(painterResource(R.drawable.phone_icon), null, Modifier.size(36.dp))
                                Column(Modifier.weight(1f).padding(horizontal = 10.dp)) {
                                    Text("חיבור וזיהוי אוטומטי", color = VehicleInk, fontWeight = FontWeight.Bold)
                                    Text(if (v.readOnly) "לא פעיל" else companion.summary, color = VehicleInk)
                                    if (!v.readOnly) companion.friendlyName?.let { Text(it, color = VehicleInk, fontSize = 13.sp) }
                                }
                                if (!v.readOnly) IconButton(openCompanion) {
                                    Image(painterResource(R.drawable.ic_chevron_back), "פתיחת חיבור וזיהוי אוטומטי", Modifier.size(22.dp))
                                }
                            }
                            if (v.readOnly) Text("הגדרות הקישור אינן פעילות לרכב זה", fontSize = 13.sp, color = Color.Gray)
                            else if (companion.health == CompanionHealth.UNKNOWN) TextButton(refreshCompanion) { Text("רענון") }
                        }
                        VehiclePanel {
                            SectionHeading("טיפולים", if (s.canManage) R.drawable.ic_add else null) { model.open(VehicleDialog.MAINTENANCE) }
                            when {
                                s.maintenanceLoading -> LinearProgressIndicator(Modifier.fillMaxWidth())
                                s.maintenanceError -> { Text("לא ניתן לטעון טיפולים"); TextButton(model::refreshMaintenance) { Text("נסה שוב") } }
                                s.maintenance.isEmpty() -> Text("אין טיפולים להצגה", color = Color(0xFF788699))
                                else -> s.maintenance.forEach { item ->
                                    Row(Modifier.fillMaxWidth().border(1.dp, VehicleBorder, RoundedCornerShape(14.dp)).padding(12.dp),
                                        verticalAlignment = Alignment.CenterVertically) {
                                        Image(painterResource(R.drawable.maintenance_icon), null, Modifier.size(28.dp))
                                        Column(Modifier.padding(start = 10.dp)) {
                                            Text(item.description, color = VehicleInk, fontWeight = FontWeight.Medium)
                                            Row(verticalAlignment = Alignment.CenterVertically) {
                                                Image(painterResource(R.drawable.ic_calender), null, Modifier.size(17.dp))
                                                Text(item.date.format(DateTimeFormatter.ofPattern("dd/MM/yyyy")), Modifier.padding(start = 6.dp), color = VehicleInk)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        VehiclePanel {
                            SectionHeading("פרטי רכב", if (s.canManage) R.drawable.ic_edit else null) { model.open(VehicleDialog.EDIT) }
                            listOf("שם הרכב" to v.name, "סוג רכב" to v.category?.label, "יצרן" to v.manufacturerName,
                                "דגם" to v.model, "מספר רכב" to v.plate).forEach { (label, value) ->
                                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                    Text(label, Modifier.weight(1f), color = VehicleInk)
                                    Text(value ?: "—", Modifier.weight(1.4f), color = VehicleInk)
                                }
                            }
                        }
                        if (s.canManage) OutlinedButton({ model.open(VehicleDialog.RETIRE) }, Modifier.fillMaxWidth(),
                            colors = ButtonDefaults.outlinedButtonColors(contentColor = Color(0xFFBD2626)),
                            border = BorderStroke(1.dp, Color(0xFFEBCACA))) {
                            Image(painterResource(R.drawable.trash_icon), null, Modifier.size(24.dp))
                            Text("הוצאת הרכב משימוש", Modifier.padding(8.dp))
                        }
                        if (v.readOnly) VehiclePanel {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Image(painterResource(R.drawable.info_icon), null, Modifier.size(24.dp))
                                Text("רכב זה אינו פעיל\nלא ניתן לבצע שינויים או פעולות ברכב זה", Modifier.padding(start = 10.dp), color = VehicleInk)
                            }
                        }
                    }
                }
            }
        }
        VehicleDetailsDialog(model)
    }
}

@Composable
private fun SectionHeading(title: String, action: Int?, click: () -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(title, Modifier.weight(1f), fontSize = 20.sp, fontWeight = FontWeight.Bold, color = VehicleInk)
        if (action != null) IconButton(click) { Image(painterResource(action), title, Modifier.size(25.dp)) }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun VehicleDetailsDialog(model: VehicleDetailsViewModel) {
    val s = model.state
    val dialog = s.dialog ?: return
    val context = LocalContext.current
    ModalBottomSheet(onDismissRequest = model::close, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = Color(0xFFF9FAFA)) {
        Column(Modifier.fillMaxWidth().imePadding().verticalScroll(rememberScrollState()).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)) {
            val title = when (dialog) { VehicleDialog.EDIT -> "עריכת פרטי רכב"; VehicleDialog.MAINTENANCE -> "הוספת טיפול"; VehicleDialog.RETIRE -> "להוציא את הרכב משימוש?" }
            Text(title, fontSize = 23.sp, fontWeight = FontWeight.Bold, color = VehicleInk)
            when (dialog) {
                VehicleDialog.RETIRE -> {
                    Image(painterResource(R.drawable.trash_icon), null, Modifier.size(36.dp).align(Alignment.CenterHorizontally))
                    Text("הרכב יישאר בהיסטוריה ולא יהיה זמין לשימוש ולהזמנות חדשות. הזמנות פעילות שטרם הסתיימו, כולל הזמנות עתידיות, יבוטלו. לא ניתן להחזיר את הרכב לפעילות.", color = VehicleInk)
                }
                VehicleDialog.MAINTENANCE -> {
                    OutlinedTextField(s.description, { model.maintenanceDraft(it, s.date) }, enabled = !s.busy,
                        label = { Text("תיאור הטיפול") }, modifier = Modifier.fillMaxWidth())
                    OutlinedButton(onClick = {
                        DatePickerDialog(context, { _, year, month, day -> model.maintenanceDraft(s.description, LocalDate.of(year, month + 1, day)) },
                            s.date.year, s.date.monthValue - 1, s.date.dayOfMonth).show()
                    }, enabled = !s.busy, modifier = Modifier.fillMaxWidth()) {
                        Image(painterResource(R.drawable.ic_calender), null, Modifier.size(22.dp))
                        Text(s.date.format(DateTimeFormatter.ofPattern("dd/MM/yyyy")), Modifier.padding(8.dp))
                    }
                }
                VehicleDialog.EDIT -> VehicleEditFields(model)
            }
            s.operationError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            val valid = when (dialog) {
                VehicleDialog.EDIT -> s.draft.valid && s.draft.manufacturer in s.catalog
                VehicleDialog.MAINTENANCE -> s.description.isNotBlank()
                VehicleDialog.RETIRE -> true
            }
            Button(model::submit, enabled = valid && !s.busy, modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(containerColor = if (dialog == VehicleDialog.RETIRE) Color(0xFFBD2626) else VehicleInk)) {
                Text(if (s.busy) "ממתינים לאישור…" else when (dialog) {
                    VehicleDialog.EDIT -> "שמירה"; VehicleDialog.MAINTENANCE -> "הוספת טיפול"; VehicleDialog.RETIRE -> "הוצאה משימוש"
                })
            }
            TextButton(model::close, enabled = !s.busy, modifier = Modifier.fillMaxWidth()) { Text("ביטול") }
        }
    }
}

@Composable
private fun VehicleEditFields(model: VehicleDetailsViewModel) {
    val s = model.state
    val d = s.draft
    OutlinedTextField(d.name, { model.edit(d.copy(name = it)) }, label = { Text("שם הרכב") }, enabled = !s.busy, modifier = Modifier.fillMaxWidth())
    Text("סוג רכב", color = VehicleInk)
    CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            VehicleCategory.entries.forEach { category ->
                Column(Modifier.weight(1f).border(if (d.category == category) 2.dp else 1.dp,
                    if (d.category == category) VehicleInk else VehicleBorder, RoundedCornerShape(12.dp))
                    .clickable(enabled = !s.busy) { model.edit(d.copy(category = category)) }.padding(3.dp),
                    horizontalAlignment = Alignment.CenterHorizontally) {
                    Image(painterResource(vehicleIllustration(category)), category.label, Modifier.fillMaxWidth().height(42.dp))
                    Text(category.label, fontSize = 9.sp, maxLines = 2)
                }
            }
        }
    }
    OutlinedTextField(d.manufacturerQuery, model::query, label = { Text("יצרן") }, enabled = !s.busy, modifier = Modifier.fillMaxWidth())
    if (s.catalogLoading) LinearProgressIndicator(Modifier.fillMaxWidth())
    if (s.catalogError) TextButton(model::loadCatalog) { Text("טעינת יצרנים מחדש") }
    if (s.catalogLoaded && showManufacturerSuggestions(d.manufacturerQuery, d.manufacturer)) {
        Column(Modifier.heightIn(max = 144.dp).verticalScroll(rememberScrollState())) {
            s.matches.forEach { manufacturer -> TextButton({ model.choose(manufacturer) }, enabled = !s.busy) { Text(manufacturer.name) } }
        }
    }
    OutlinedTextField(d.model, { model.edit(d.copy(model = it)) }, label = { Text("דגם") }, enabled = !s.busy, modifier = Modifier.fillMaxWidth())
    OutlinedTextField(d.plate, { model.edit(d.copy(plate = it)) }, label = { Text("מספר רכב") }, enabled = !s.busy, modifier = Modifier.fillMaxWidth())
}

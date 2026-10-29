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
        val wordmarkBlend = if (LocalFcaDark.current) BlendMode.SrcOver else BlendMode.Multiply
        Image(painterResource(if (LocalFcaDark.current) R.drawable.family_car_agent_road_logo_1__dark else R.drawable.fca_header_wordmark), "Family Car Agent",
            Modifier.align(Alignment.Center).fillMaxWidth(.63f).height(58.dp).graphicsLayer {
                compositingStrategy = CompositingStrategy.Offscreen; blendMode = wordmarkBlend
            }, contentScale = ContentScale.Fit)
        IconButton(back, Modifier.align(AbsoluteAlignment.CenterRight).size(46.dp)
            .background(fcaColor(Color.White, FcaColorRole.SURFACE).copy(alpha = .85f), CircleShape)) {
            Image(painterResource(R.drawable.ic_chevron_back), "חזרה", Modifier.size(22.dp), colorFilter = fcaControlIconFilter())
        }
    }
}

@Composable
internal fun VehiclePanel(content: @Composable ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxWidth().background(fcaColor(Color.White, FcaColorRole.SURFACE).copy(alpha = .72f), RoundedCornerShape(18.dp))
        .border(1.dp, VehicleBorder, RoundedCornerShape(18.dp)).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp), content = content)
}

@Composable
internal fun VehicleDetailsScreen(model: VehicleDetailsViewModel, companion: CompanionPresentation,
    back: () -> Unit, openCompanion: () -> Unit, refreshCompanion: () -> Unit) {
    val s = model.state
    BackHandler { if (s.dialog != null) model.close() else back() }
    if (blockingInitialLoadError(s.loading, s.error, s.detail != null)) {
        FcaErrorScreen("לא ניתן לטעון את פרטי הרכב", model::refresh, "חזרה לרכבים", back)
        return
    }
    CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
        Column(Modifier.fillMaxSize().background(fcaColor(Color(0xFFF6F7F7), FcaColorRole.BACKGROUND)).navigationBarsPadding(),
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
                        Column(
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(0.dp)
                        ) {
                            Text(
                                v.name,
                                fontSize = 30.sp,
                                color = VehicleInk,
                                fontWeight = FontWeight.Bold
                            )

                            CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) {
                                Image(
                                    painterResource(vehicleIllustration(v.category)),
                                    null,
                                    Modifier
                                        .fillMaxWidth(.9f)
                                        .height(200.dp)
                                        .alpha(if (v.readOnly) .55f else 1f),
                                    contentScale = ContentScale.Fit
                                )
                            }
                        }
                        val statusColor = if (v.readOnly) fcaColor(Color(0xFF7A8795), FcaColorRole.SECONDARY) else if (detail.inUse) fcaColor(Color(0xFF9B631A), FcaColorRole.WARNING) else fcaColor(Color(0xFF168153), FcaColorRole.SUCCESS)
                        Text(detail.status, Modifier.fillMaxWidth().background(statusColor.copy(alpha = .10f), RoundedCornerShape(16.dp))
                            .padding(10.dp), color = statusColor, fontWeight = FontWeight.Bold, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                        VehiclePanel {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Image(painterResource(R.drawable.phone_icon), null, Modifier.size(36.dp), colorFilter = fcaControlIconFilter())
                                Column(Modifier.weight(1f).padding(horizontal = 10.dp)) {
                                    Text("חיבור וזיהוי אוטומטי", color = VehicleInk, fontWeight = FontWeight.Bold)
                                    Text(if (v.readOnly) "לא פעיל" else companion.summary, color = VehicleInk)
                                    if (!v.readOnly) companion.friendlyName?.let { Text(it, color = VehicleInk, fontSize = 13.sp) }
                                }
                                if (!v.readOnly) IconButton(openCompanion) {
                                    Image(painterResource(R.drawable.ic_chevron_right), "פתיחת חיבור וזיהוי אוטומטי", Modifier.size(22.dp), colorFilter = fcaControlIconFilter())
                                }
                            }
                            if (v.readOnly) Text("הגדרות הקישור אינן פעילות לרכב זה", fontSize = 13.sp, color = fcaColor(Color.Gray, FcaColorRole.SECONDARY))
                        }
                        VehiclePanel {
                            SectionHeading("טיפולים", if (s.canManage) R.drawable.ic_add else null) { model.open(VehicleDialog.MAINTENANCE) }
                            when {
                                s.maintenanceLoading -> LinearProgressIndicator(Modifier.fillMaxWidth())
                                s.maintenanceError -> { Text("לא ניתן לטעון טיפולים"); TextButton(model::refreshMaintenance) { Text("נסה שוב") } }
                                s.maintenance.isEmpty() -> Text("אין טיפולים להצגה", color = fcaColor(Color(0xFF788699), FcaColorRole.SECONDARY))
                                else -> s.maintenance.forEach { item ->
                                    Row(Modifier.fillMaxWidth().border(1.dp, VehicleBorder, RoundedCornerShape(14.dp))
                                        .clickable(enabled = s.canManage && !s.busy) { model.openMaintenance(item) }.padding(12.dp),
                                        verticalAlignment = Alignment.CenterVertically) {
                                        Image(painterResource(R.drawable.maintenance_icon), null, Modifier.size(28.dp), colorFilter = fcaControlIconFilter())
                                        Column(Modifier.padding(start = 10.dp)) {
                                            Text(item.description, color = VehicleInk, fontWeight = FontWeight.Medium)
                                            if (item.completed) Text("בוצע", color = fcaColor(Color(0xFF788699), FcaColorRole.SECONDARY))
                                            Row(verticalAlignment = Alignment.CenterVertically) {
                                                Image(painterResource(R.drawable.ic_calender), null, Modifier.size(17.dp), colorFilter = fcaControlIconFilter())
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
                            colors = ButtonDefaults.outlinedButtonColors(contentColor = fcaColor(Color(0xFFBD2626), FcaColorRole.DANGER)),
                            border = BorderStroke(1.dp, fcaColor(Color(0xFFEBCACA), FcaColorRole.DANGER_SURFACE))) {
                            Image(painterResource(R.drawable.trash_icon), null, Modifier.size(40.dp), colorFilter = fcaControlIconFilter())
                            Text("הוצאת הרכב משימוש", Modifier.padding(horizontal = 2.dp, vertical = 2.dp))
                        }
                        if (v.readOnly) VehiclePanel {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Image(painterResource(R.drawable.info_icon), null, Modifier.size(24.dp), colorFilter = fcaControlIconFilter())
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
        if (action != null) IconButton(click) { Image(painterResource(action), title, Modifier.size(25.dp), colorFilter = fcaControlIconFilter()) }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun VehicleDetailsDialog(model: VehicleDetailsViewModel) {
    val s = model.state
    val dialog = s.dialog ?: return
    val context = LocalContext.current
    val pickerContext = android.view.ContextThemeWrapper(context, if (LocalFcaDark.current)
        R.style.Theme_Fca_Companion_Dark else R.style.Theme_Fca_Companion_Light)
    ModalBottomSheet(onDismissRequest = model::close, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = fcaColor(Color(0xFFF9FAFA), FcaColorRole.SURFACE)) {
        Column(Modifier.fillMaxWidth().imePadding().verticalScroll(rememberScrollState()).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)) {
            val title = when (dialog) { VehicleDialog.EDIT -> "עריכת פרטי רכב"; VehicleDialog.MAINTENANCE -> if (s.maintenanceRef == null) "הוספת טיפול" else "עריכת טיפול"; VehicleDialog.RETIRE -> "להוציא את הרכב משימוש?" }
            Text(title, fontSize = 23.sp, fontWeight = FontWeight.Bold, color = VehicleInk)
            when (dialog) {
                VehicleDialog.RETIRE -> {
                    Image(painterResource(R.drawable.trash_icon), null, Modifier.size(36.dp).align(Alignment.CenterHorizontally), colorFilter = fcaControlIconFilter())
                    Text("הרכב יישאר בהיסטוריה ולא יהיה זמין לשימוש ולהזמנות חדשות. הזמנות פעילות שטרם הסתיימו, כולל הזמנות עתידיות, יבוטלו. לא ניתן להחזיר את הרכב לפעילות.", color = VehicleInk)
                }
                VehicleDialog.MAINTENANCE -> {
                    OutlinedTextField(s.description, { model.maintenanceDraft(it, s.date) }, enabled = !s.busy,
                        label = { Text("תיאור הטיפול") }, modifier = Modifier.fillMaxWidth())
                    OutlinedButton(onClick = {
                        DatePickerDialog(pickerContext, { _, year, month, day -> model.maintenanceDraft(s.description, LocalDate.of(year, month + 1, day)) },
                            s.date.year, s.date.monthValue - 1, s.date.dayOfMonth).show()
                    }, enabled = !s.busy, modifier = Modifier.fillMaxWidth()) {
                        Image(painterResource(R.drawable.ic_calender), null, Modifier.size(22.dp), colorFilter = fcaControlIconFilter())
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
                colors = ButtonDefaults.buttonColors(containerColor = if (dialog == VehicleDialog.RETIRE) fcaColor(Color(0xFFBD2626), FcaColorRole.DANGER) else VehicleInk)) {
                Text(if (s.busy) "ממתינים לאישור…" else when (dialog) {
                    VehicleDialog.EDIT -> "שמירה"; VehicleDialog.MAINTENANCE -> if (s.maintenanceRef == null) "הוספת טיפול" else "שמירה"; VehicleDialog.RETIRE -> "הוצאה משימוש"
                })
            }
            if (dialog == VehicleDialog.MAINTENANCE && s.maintenanceRef != null) {
                if (s.maintenance.any { it.ref == s.maintenanceRef && !it.completed }) {
                    TextButton(model::completeMaintenance, enabled = !s.busy, modifier = Modifier.fillMaxWidth()) {
                        Text("סימון הטיפול כבוצע")
                    }
                } else {
                    Text("הטיפול בוצע")
                }
                TextButton(model::requestDelete, enabled = !s.busy, modifier = Modifier.fillMaxWidth()) {
                    Text("מחיקת טיפול", color = MaterialTheme.colorScheme.error)
                }
            }
            TextButton(model::close, enabled = !s.busy, modifier = Modifier.fillMaxWidth()) { Text("ביטול") }
        }
    }
    if (s.confirmDelete) AlertDialog(onDismissRequest = model::cancelDelete,
        title = { Text("למחוק את הטיפול?") },
        text = { Column {
            Text("הטיפול יימחק מהרכב. לא ניתן לבטל את המחיקה.")
            s.operationError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        } },
        confirmButton = { TextButton(model::submit, enabled = !s.busy) { Text("מחיקה", color = MaterialTheme.colorScheme.error) } },
        dismissButton = { TextButton(model::cancelDelete, enabled = !s.busy) { Text("ביטול") } })
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

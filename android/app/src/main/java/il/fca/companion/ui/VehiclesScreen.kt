package il.fca.companion.ui

import androidx.activity.compose.BackHandler
import androidx.activity.compose.LocalActivity
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.AbsoluteAlignment
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import il.fca.companion.R
import il.fca.companion.net.*

internal val VehicleInk: Color
    @Composable get() = fcaColor(Color(0xFF23364E), FcaColorRole.TEXT)
internal val VehicleBorder: Color
    @Composable get() = fcaColor(Color(0xFFDDE2E8), FcaColorRole.BORDER)
internal fun vehicleIllustration(category: VehicleCategory?): Int = when (category) {
    VehicleCategory.HATCHBACK -> R.drawable.vehicle_hatchback
    VehicleCategory.SEDAN -> R.drawable.vehicle_sedan
    VehicleCategory.CROSSOVER -> R.drawable.vehicle_crossover
    VehicleCategory.MINIVAN -> R.drawable.vehicle_minivan
    VehicleCategory.SUV -> R.drawable.vehicle_suv
    null -> R.drawable.single_car_icon
}

@Composable
internal fun VehiclesScreen(model: VehiclesViewModel, familyId: Long?, back: () -> Unit) {
    val activity = LocalActivity.current
    DisposableEffect(model, familyId) {
        model.start()
        onDispose {
            // Activity recreation must not discard an uncertain POST's retry identity.
            if (activity?.isChangingConfigurations != true) model.pause()
        }
    }
    val state = model.state
    val navigateBack = { if (!model.back()) back() }
    if (state.page == VehiclesPage.PLACEHOLDER && state.selected != null) {
        VehicleDetailsRoute(state.selected.ref, model::currentIdentity, navigateBack)
        return
    }
    BackHandler { navigateBack() }
    if (state.page == VehiclesPage.LIST && blockingInitialLoadError(state.loading, state.loadError, state.loaded)) {
        FcaErrorScreen("לא ניתן לטעון את הרכבים", model::refresh, "חזרה לדשבורד", navigateBack)
        return
    }
    Column(Modifier.fillMaxSize().background(fcaColor(Color(0xFFF6F7F7), FcaColorRole.BACKGROUND)).navigationBarsPadding(),
        horizontalAlignment = Alignment.CenterHorizontally) {
        Column(Modifier.widthIn(max = 620.dp).fillMaxSize()) {
            VehiclesHeader(if (state.page == VehiclesPage.ADD) "הוספת רכב" else "רכבים", navigateBack)
            when (state.page) {
                VehiclesPage.ADD -> AddVehicleScreen(model)
                VehiclesPage.PLACEHOLDER -> Unit // VehicleDetailsRoute owns the selected-vehicle flow above.
                VehiclesPage.LIST -> when {
                    state.loading && !state.loaded -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                    state.loadError -> Column(Modifier.fillMaxWidth().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                        Text("לא ניתן לטעון את הרכבים", color = VehicleInk)
                        TextButton(onClick = model::refresh) { Text("נסה שוב") }
                    }
                    state.loaded && state.rows.isEmpty() -> Column(Modifier.fillMaxSize().padding(24.dp),
                        verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
                        Image(painterResource(R.drawable.no_cars_icon), null, Modifier.size(132.dp))
                        Spacer(Modifier.height(24.dp))
                        Text("אין עדיין רכבים", color = VehicleInk, fontSize = 26.sp, fontWeight = FontWeight.Bold)
                        if (state.canCreate) {
                            Spacer(Modifier.height(16.dp))
                            Text("הוסיפו את הרכב הראשון של המשפחה\nכדי להתחיל לנהל אותו כאן",
                                color = fcaColor(Color(0xFF788699), FcaColorRole.SECONDARY), fontSize = 18.sp, lineHeight = 26.sp,
                                textAlign = TextAlign.Center)
                            Spacer(Modifier.height(28.dp))
                            OutlinedButton(onClick = model::add, modifier = Modifier.fillMaxWidth().height(56.dp),
                                shape = RoundedCornerShape(22.dp), border = BorderStroke(1.dp, VehicleInk)) {
                                Text("הוספת רכב", color = VehicleInk, fontSize = 20.sp)
                                Spacer(Modifier.width(12.dp))
                                Image(painterResource(R.drawable.ic_add), null, Modifier.size(24.dp))
                            }
                            Spacer(Modifier.height(14.dp))
                            Text("זמין למנהל המשפחה בלבד", color = fcaColor(Color(0xFF788699), FcaColorRole.SECONDARY),
                                fontSize = 14.sp, textAlign = TextAlign.Center)
                        } else {
                            Spacer(Modifier.height(16.dp))
                            Text("כרגע אין רכבים במשפחה\nרק מנהל המשפחה יכול להוסיף רכבים",
                                color = fcaColor(Color(0xFF788699), FcaColorRole.SECONDARY), fontSize = 18.sp, lineHeight = 26.sp,
                                textAlign = TextAlign.Center)
                        }
                    }
                    else -> LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(20.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        item {
                            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                Text("הרכבים שלנו", Modifier.weight(1f), color = VehicleInk, fontSize = 21.sp, fontWeight = FontWeight.Bold)
                                if (state.canCreate) IconButton(onClick = model::add,
                                    modifier = Modifier.border(1.dp, VehicleBorder, CircleShape)) {
                                    Image(painterResource(R.drawable.ic_add), "הוספת רכב", Modifier.size(24.dp))
                                }
                            }
                        }
                        items(state.active, key = { it.ref }) { vehicle -> VehicleCard(vehicle) { model.select(vehicle) } }
                        if (state.retired.isNotEmpty()) {
                            item {
                                Column(Modifier.padding(top = 22.dp, bottom = 10.dp)) {
                                    HorizontalDivider(color = VehicleBorder)
                                    Text("רכבים לא פעילים", Modifier.padding(top = 22.dp), color = fcaColor(Color(0xFF788699), FcaColorRole.SECONDARY),
                                        fontSize = 20.sp, fontWeight = FontWeight.Bold)
                                }
                            }
                            items(state.retired, key = { it.ref }) { vehicle -> VehicleCard(vehicle) { model.select(vehicle) } }
                        }
                    }
                }
            }
        }
    }
}

@Composable
internal fun VehiclesHeader(title: String, back: () -> Unit) {
    Box(Modifier.fillMaxWidth().height(76.dp).padding(horizontal = 16.dp)) {
        val wordmarkBlend = if (LocalFcaDark.current) BlendMode.SrcOver else BlendMode.Multiply
        Image(painterResource(if (LocalFcaDark.current) R.drawable.family_car_agent_road_logo_1__dark else R.drawable.fca_header_wordmark), "Family Car Agent",
            Modifier.align(Alignment.Center).fillMaxWidth(.63f).height(58.dp).graphicsLayer {
                compositingStrategy = CompositingStrategy.Offscreen
                blendMode = wordmarkBlend
            }, contentScale = ContentScale.Fit)
        IconButton(onClick = back, modifier = Modifier.align(AbsoluteAlignment.CenterRight)
            .size(46.dp).background(fcaColor(Color.White, FcaColorRole.SURFACE).copy(alpha = .85f), CircleShape)) {
            Image(painterResource(R.drawable.ic_chevron_back), "חזרה", Modifier.size(22.dp), colorFilter = fcaControlIconFilter())
        }
    }
    if (title == "רכבים") {
        // The approved artwork includes the title; preserve its full canvas, as in History.
        Box(Modifier.fillMaxWidth().height(108.dp), contentAlignment = Alignment.Center) {
            Image(painterResource(R.drawable.vehicles_icon), "רכבים",
                Modifier.requiredSize(200.dp).offset(y = (-15).dp), contentScale = ContentScale.Fit, colorFilter = fcaControlIconFilter())
        }
    } else Row(Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 24.dp), horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically) {
        Image(painterResource(R.drawable.single_car_icon), null, Modifier.size(40.dp), colorFilter = fcaControlIconFilter())
        Spacer(Modifier.width(12.dp))
        Text(title, color = VehicleInk, fontWeight = FontWeight.Bold, fontSize = 27.sp)
    }
}

@Composable
private fun VehicleCard(vehicle: ManagedVehicle, open: () -> Unit) {
    Row(Modifier.fillMaxWidth().heightIn(min = 94.dp).alpha(if (vehicle.readOnly) .5f else 1f)
        .clip(RoundedCornerShape(24.dp)).background(fcaColor(Color.White, FcaColorRole.SURFACE).copy(alpha = .7f))
        .border(1.dp, VehicleBorder, RoundedCornerShape(24.dp)).clickable(onClick = open).padding(16.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Image(painterResource(R.drawable.ic_chevron_back), null, Modifier.size(18.dp), colorFilter = fcaControlIconFilter())
        Text(vehicle.name, Modifier.weight(1f).padding(horizontal = 16.dp), color = VehicleInk,
            fontSize = 22.sp, fontWeight = FontWeight.Bold)
        // Entire illustration is preserved, never tinted or mirrored for RTL.
        CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) {
            Image(painterResource(vehicleIllustration(vehicle.category)), null, Modifier.width(112.dp).height(64.dp),
                contentScale = ContentScale.Fit)
        }
    }
}

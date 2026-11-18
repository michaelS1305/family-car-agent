package il.fca.companion.ui

import android.annotation.SuppressLint
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.TextButton
import android.util.Log
import androidx.lifecycle.repeatOnLifecycle
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.google.android.gms.common.ConnectionResult
import com.google.android.gms.common.GoogleApiAvailability
import com.google.android.gms.maps.CameraUpdateFactory
import com.google.android.gms.maps.GoogleMapOptions
import com.google.android.gms.maps.MapView
import com.google.android.gms.maps.model.LatLng
import com.google.android.gms.maps.model.MarkerOptions
import il.fca.companion.BuildConfig
import il.fca.companion.net.VerifiedLocation
import kotlinx.coroutines.delay

/** Visual-only candidate preview. Never reads or writes Companion's saved home. */
@Composable
internal fun VerifiedAddressMap(location: VerifiedLocation?, modifier: Modifier = Modifier) {
    // Object identity ties callbacks to this resolution, even at identical coordinates.
    key(location) {
        if (location == null || !BuildConfig.ADDRESS_MAPS_ENABLED) {
            Box(modifier, contentAlignment = Alignment.Center) { Text("תצוגת מפה אינה זמינה") }
        } else CandidateMap(location, modifier)
    }
}

internal enum class MapLoadPhase { LOADING, LOADED, SLOW, FAILED }

/** Per-attempt state: callbacks cannot revive a disposed/retried candidate. */
internal class MapLoadAttempt {
    var phase by mutableStateOf(MapLoadPhase.LOADING); private set
    var retryReady by mutableStateOf(false); private set
    var active = true; private set
    fun loaded() { if (active && phase != MapLoadPhase.FAILED) phase = MapLoadPhase.LOADED }
    fun timeout() { if (active && phase == MapLoadPhase.LOADING) phase = MapLoadPhase.SLOW }
    fun failed() { if (active) phase = MapLoadPhase.FAILED }
    fun allowRetry() { if (active) retryReady = true }
    val canRetry get() = active && retryReady && phase in setOf(MapLoadPhase.SLOW, MapLoadPhase.FAILED)
    fun retry(): Boolean {
        if (!canRetry) return false
        active = false // Fence callbacks immediately, before Compose disposes the old view.
        return true
    }
    fun dispose() { active = false }
}

private fun mapDiagnostic(stage: String) {
    // Callers supply fixed stage names only; never include exceptions, keys or coordinates.
    if (BuildConfig.DEBUG) Log.d("FCA_ADDRESS_MAP", "event=$stage")
}

@Composable
private fun CandidateMap(location: VerifiedLocation, modifier: Modifier) {
    var generation by remember { mutableIntStateOf(0) }
    key(generation) { MapAttempt(location, modifier) { generation++ } }
}

// This preview intentionally has no touch actions; confirmation lives outside it.
@SuppressLint("ClickableViewAccessibility")
@Composable
private fun MapAttempt(location: VerifiedLocation, modifier: Modifier, retry: () -> Unit) {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val attempt = remember { MapLoadAttempt() }
    val mapView = remember {
        runCatching {
            check(GoogleApiAvailability.getInstance().isGooglePlayServicesAvailable(context) == ConnectionResult.SUCCESS)
            MapView(context, GoogleMapOptions().liteMode(true).mapToolbarEnabled(false))
        }.onFailure { attempt.failed(); mapDiagnostic("initialization_failed") }.getOrNull()
    }
    var initialized by remember { mutableStateOf(false) }
    DisposableEffect(mapView, lifecycle) {
        var started = false
        var resumed = false
        fun safe(stage: String, action: () -> Unit) {
            runCatching(action).onFailure { attempt.failed(); mapDiagnostic(stage) }
        }
        fun sync() {
            if (!attempt.active || !initialized) return
            val wantsResume = lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)
            val wantsStart = lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)
            if (resumed && !wantsResume) { resumed = false; safe("pause_failed") { mapView?.onPause() } }
            if (started && !wantsStart) { started = false; safe("stop_failed") { mapView?.onStop() } }
            if (!started && wantsStart) { started = true; safe("start_failed") { mapView?.onStart() } }
            if (!resumed && wantsResume) { resumed = true; safe("resume_failed") { mapView?.onResume() } }
        }
        val observer = LifecycleEventObserver { _, _ -> sync() }
        if (mapView != null) safe("create_failed") {
            mapView.onCreate(null)
            initialized = true
            mapView.isClickable = false
            mapView.isLongClickable = false
            mapView.setOnTouchListener { _, _ -> true }
            mapView.getMapAsync { map ->
                if (attempt.active) safe("configuration_failed") {
                    mapDiagnostic("ready")
                    map.uiSettings.isMapToolbarEnabled = false
                    map.uiSettings.isZoomControlsEnabled = false
                    map.uiSettings.setAllGesturesEnabled(false)
                    map.setOnMapClickListener { }
                    map.setOnMapLongClickListener { }
                    map.setOnMarkerClickListener { true }
                    map.setOnMapLoadedCallback {
                        if (attempt.active) { attempt.loaded(); mapDiagnostic("loaded") }
                    }
                    val point = LatLng(location.latitude, location.longitude)
                    map.addMarker(MarkerOptions().position(point).draggable(false))
                    map.moveCamera(CameraUpdateFactory.newLatLngZoom(point, 16f))
                }
            }
            lifecycle.addObserver(observer)
            sync()
        }
        onDispose {
            attempt.dispose()
            lifecycle.removeObserver(observer)
            // One failing cleanup must not prevent the remaining cleanup operations.
            if (resumed) safe("pause_cleanup_failed") { mapView?.onPause() }
            if (started) safe("stop_cleanup_failed") { mapView?.onStop() }
            safe("destroy_failed") { mapView?.onDestroy() }
        }
    }
    LaunchedEffect(attempt) { delay(5_000); attempt.allowRetry() }
    LaunchedEffect(attempt, lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            delay(15_000)
            attempt.timeout()
            if (attempt.phase == MapLoadPhase.SLOW) mapDiagnostic("slow")
        }
    }
    Column(modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        Box(Modifier.fillMaxWidth().weight(1f), contentAlignment = Alignment.TopCenter) {
            // Remains attached after timeout: the same instance can finish loading later.
            if (mapView != null && initialized) AndroidView(
                factory = { mapView }, modifier = Modifier.matchParentSize().graphicsLayer {
                    alpha = if (attempt.phase == MapLoadPhase.FAILED) 0f else 1f
                })
            if (attempt.phase == MapLoadPhase.LOADING) Text("טוען מפה…")
        }
        if (attempt.phase in setOf(MapLoadPhase.SLOW, MapLoadPhase.FAILED)) {
            TextButton(enabled = attempt.canRetry, onClick = { if (attempt.retry()) retry() }) {
                Text("המפה אינה זמינה · נסו שוב")
            }
        }
    }
}

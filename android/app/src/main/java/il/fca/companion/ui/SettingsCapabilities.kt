package il.fca.companion.ui

import android.Manifest
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.location.LocationManager
import android.net.Uri
import android.provider.Settings
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner

internal const val COMPANION_VEHICLES_HINT = "כדי להגדיר Android Companion, בחר רכב והיכנס ל׳חיבור וזיהוי אוטומטי׳."

internal enum class CapabilityStatus(val text: String) {
    READY("מאושר"), MISSING("נדרשת הגדרה"), UNKNOWN("טרם הוגדר")
}

internal fun locationStatus(fine: Boolean, background: Boolean, enabled: Boolean) =
    if (fine && background && enabled) CapabilityStatus.READY else CapabilityStatus.MISSING

internal fun notificationStatus(permission: Boolean, enabled: Boolean, importance: Int?) = when {
    !permission || !enabled || importance == NotificationManager.IMPORTANCE_NONE -> CapabilityStatus.MISSING
    importance == null -> CapabilityStatus.UNKNOWN // Service may not have created its channel yet.
    else -> CapabilityStatus.READY
}

internal data class SettingsCapabilities(
    val location: CapabilityStatus = CapabilityStatus.UNKNOWN,
    val notifications: CapabilityStatus = CapabilityStatus.UNKNOWN
)

internal fun readSettingsCapabilities(context: Context): SettingsCapabilities {
    fun granted(permission: String) = context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
    return SettingsCapabilities(
        location = runCatching {
            locationStatus(granted(Manifest.permission.ACCESS_FINE_LOCATION),
                granted(Manifest.permission.ACCESS_BACKGROUND_LOCATION),
                context.getSystemService(LocationManager::class.java).isLocationEnabled)
        }.getOrDefault(CapabilityStatus.UNKNOWN),
        notifications = runCatching {
            val manager = context.getSystemService(NotificationManager::class.java)
            notificationStatus(granted(Manifest.permission.POST_NOTIFICATIONS), manager.areNotificationsEnabled(),
                manager.getNotificationChannel("fca_return")?.importance)
        }.getOrDefault(CapabilityStatus.UNKNOWN)
    )
}

@Composable
internal fun rememberSettingsCapabilities(): SettingsCapabilities {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    var value by remember(context) { mutableStateOf(readSettingsCapabilities(context)) }
    DisposableEffect(context, lifecycle) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) value = readSettingsCapabilities(context)
        }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer) }
    }
    return value
}

internal fun appDetailsIntent(packageName: String) =
    Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))

internal fun notificationSettingsIntent(packageName: String) =
    Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName)

internal fun locationSettingsIntent(packageName: String, servicesEnabled: Boolean?) =
    if (servicesEnabled == false) Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS) else appDetailsIntent(packageName)

internal fun launchSettings(primary: Intent, fallback: Intent, launch: (Intent) -> Unit): Boolean {
    if (runCatching { launch(primary) }.isSuccess) return true
    return runCatching { launch(fallback) }.isSuccess
}

internal fun openCapabilitySettings(context: Context, location: Boolean) {
    val details = appDetailsIntent(context.packageName)
    val primary = if (location) locationSettingsIntent(context.packageName, runCatching {
        context.getSystemService(LocationManager::class.java).isLocationEnabled
    }.getOrNull()) else notificationSettingsIntent(context.packageName)
    launchSettings(primary, details) { context.startActivity(it) }
}

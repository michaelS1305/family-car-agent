
package il.fca.companion.ui

import android.Manifest
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.location.LocationManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner

internal const val COMPANION_VEHICLES_HINT =
    "כדי להגדיר Android Companion, בחר רכב והיכנס ל׳חיבור וזיהוי אוטומטי׳."

internal enum class CapabilityStatus(val text: String) {
    READY("מאושר"),
    MISSING("נדרשת הגדרה"),
    UNKNOWN("טרם הוגדר")
}

internal fun locationStatus(
    fine: Boolean,
    background: Boolean,
    enabled: Boolean
): CapabilityStatus =
    if (fine && background && enabled) {
        CapabilityStatus.READY
    } else {
        CapabilityStatus.MISSING
    }

internal fun notificationStatus(
    permission: Boolean,
    enabled: Boolean,
    importance: Int?
): CapabilityStatus = when {
    !permission || !enabled ->
        CapabilityStatus.MISSING

    importance == NotificationManager.IMPORTANCE_NONE ->
        CapabilityStatus.MISSING

    // A channel that has not been created yet
    // is not necessarily a disabled permission.
    else ->
        CapabilityStatus.READY
}

internal data class SettingsCapabilities(
    val location: CapabilityStatus = CapabilityStatus.UNKNOWN,
    val notifications: CapabilityStatus = CapabilityStatus.UNKNOWN
)

internal fun readSettingsCapabilities(
    context: Context
): SettingsCapabilities {

    fun granted(permission: String): Boolean =
        context.checkSelfPermission(permission) ==
                PackageManager.PERMISSION_GRANTED

    val location = runCatching {
        val locationManager =
            context.getSystemService(LocationManager::class.java)

        locationStatus(
            fine = granted(
                Manifest.permission.ACCESS_FINE_LOCATION
            ),
            background = if (
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
            ) {
                granted(
                    Manifest.permission.ACCESS_BACKGROUND_LOCATION
                )
            } else {
                true
            },
            enabled = locationManager.isLocationEnabled
        )
    }.getOrDefault(CapabilityStatus.UNKNOWN)

    val notifications = runCatching {
        val manager =
            context.getSystemService(NotificationManager::class.java)

        val permissionGranted =
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                granted(Manifest.permission.POST_NOTIFICATIONS)
            } else {
                true
            }

        val channelImportance =
            manager.getNotificationChannel(
                "fca_native_vehicle_events"
            )?.importance

        notificationStatus(
            permission = permissionGranted,
            enabled = manager.areNotificationsEnabled(),
            importance = channelImportance
        )
    }.getOrDefault(CapabilityStatus.UNKNOWN)

    return SettingsCapabilities(
        location = location,
        notifications = notifications
    )
}

@Composable
internal fun rememberSettingsCapabilities(): SettingsCapabilities {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle

    var value by remember(context) {
        mutableStateOf(readSettingsCapabilities(context))
    }

    DisposableEffect(context, lifecycle) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                value = readSettingsCapabilities(context)
            }
        }

        lifecycle.addObserver(observer)

        onDispose {
            lifecycle.removeObserver(observer)
        }
    }

    return value
}

internal fun appDetailsIntent(packageName: String): Intent =
    Intent(
        Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
        Uri.parse("package:$packageName")
    )

internal fun notificationSettingsIntent(packageName: String): Intent =
    Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
        .putExtra(Settings.EXTRA_APP_PACKAGE, packageName)

internal fun locationSettingsIntent(
    packageName: String,
    servicesEnabled: Boolean?
): Intent =
    if (servicesEnabled == false) {
        Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS)
    } else {
        appDetailsIntent(packageName)
    }

internal fun launchSettings(
    primary: Intent,
    fallback: Intent,
    launch: (Intent) -> Unit
): Boolean {
    if (runCatching { launch(primary) }.isSuccess) {
        return true
    }

    return runCatching { launch(fallback) }.isSuccess
}

internal fun openCapabilitySettings(
    context: Context,
    location: Boolean
) {
    val details = appDetailsIntent(context.packageName)

    val primary = if (location) {
        locationSettingsIntent(
            context.packageName,
            runCatching {
                context.getSystemService(
                    LocationManager::class.java
                ).isLocationEnabled
            }.getOrNull()
        )
    } else {
        notificationSettingsIntent(context.packageName)
    }

    launchSettings(primary, details) { intent ->
        context.startActivity(intent)
    }
}

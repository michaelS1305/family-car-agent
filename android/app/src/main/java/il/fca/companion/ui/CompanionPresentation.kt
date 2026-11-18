package il.fca.companion.ui

import android.Manifest
import android.bluetooth.BluetoothManager
import android.companion.CompanionDeviceManager
import android.content.pm.PackageManager
import android.location.LocationManager
import android.os.Build
import il.fca.companion.FcaApplication
import org.json.JSONArray

internal enum class CompanionHealth { READY, SETUP, ACTION, UNKNOWN, RETIRED }
internal enum class DeviceHealth { REGISTERED, MISSING, INVALID, UNKNOWN }
internal fun companionStatusText(loading: Boolean, resolved: String) = if (loading) "בודק…" else resolved
internal data class CompanionPresentation(
    val health: CompanionHealth = CompanionHealth.UNKNOWN,
    val device: DeviceHealth = DeviceHealth.UNKNOWN,
    val bluetooth: CompanionHealth = CompanionHealth.UNKNOWN,
    val detection: CompanionHealth = CompanionHealth.UNKNOWN,
    val friendlyName: String? = null
) {
    val summary get() = when (health) {
        CompanionHealth.READY -> "פעיל"
        CompanionHealth.SETUP -> "לא מוגדר"
        CompanionHealth.ACTION -> "נדרשת פעולה"
        CompanionHealth.UNKNOWN -> "לא ניתן לאמת כרגע"
        CompanionHealth.RETIRED -> "לא פעיל"
    }
    val overall get() = when (health) {
        CompanionHealth.READY -> "הזיהוי האוטומטי פעיל"
        CompanionHealth.SETUP -> "נדרשת השלמת הגדרה"
        else -> summary
    }
}

internal fun companionPresentation(device: DeviceHealth, local: Boolean, binding: Boolean?,
    systemMatches: Boolean?, bluetoothEnabled: Boolean?, locationReady: Boolean, homeReady: Boolean,
    name: String?, observationVerified: Boolean = false): CompanionPresentation {
    val bluetooth = when {
        !local -> CompanionHealth.SETUP
        binding == false || systemMatches == false -> CompanionHealth.ACTION
        binding == null || systemMatches == null || bluetoothEnabled == null -> CompanionHealth.UNKNOWN
        !bluetoothEnabled -> CompanionHealth.ACTION
        else -> CompanionHealth.READY
    }
    val detection = when {
        device == DeviceHealth.MISSING || !local -> CompanionHealth.SETUP
        !locationReady -> CompanionHealth.SETUP
        !homeReady -> CompanionHealth.UNKNOWN
        device == DeviceHealth.REGISTERED && bluetooth == CompanionHealth.READY && observationVerified -> CompanionHealth.READY
        else -> CompanionHealth.UNKNOWN
    }
    val health = when {
        device == DeviceHealth.UNKNOWN -> CompanionHealth.UNKNOWN
        device == DeviceHealth.INVALID -> CompanionHealth.ACTION
        device == DeviceHealth.MISSING -> CompanionHealth.SETUP
        bluetooth == CompanionHealth.ACTION -> CompanionHealth.ACTION
        bluetooth == CompanionHealth.UNKNOWN -> CompanionHealth.UNKNOWN
        bluetooth == CompanionHealth.SETUP || detection == CompanionHealth.SETUP -> CompanionHealth.SETUP
        else -> detection
    }
    return CompanionPresentation(health, device, bluetooth, detection, name)
}

/** Snapshot using existing store getters. Never removes bindings or changes observation. IO thread only. */
internal fun readCompanionPresentation(app: FcaApplication, owner: String, vehicle: String): CompanionPresentation {
    fun current() = app.store.activeOwner() == owner && app.auth.owner() == owner
    if (!current()) return CompanionPresentation()
    return try {
        val installation = app.store.installation(owner)
        val local = app.store.associations(owner).singleOrNull { it.vehicle == vehicle }
        var binding: Boolean? = null
        val device = if (installation.device == null) DeviceHealth.MISSING else {
            val devices = JSONArray(app.api.call(owner, "/api/devices"))
            val row = (0 until devices.length()).map { devices.getJSONObject(it) }
                .singleOrNull { it.getString("device_ref") == installation.device }
            if (row == null || !row.isNull("revoked_at")) DeviceHealth.INVALID else {
                val bindings = JSONArray(app.api.call(owner, "/api/devices/${installation.device}/vehicle-bindings"))
                binding = (0 until bindings.length()).map { bindings.getJSONObject(it) }
                    .any { it.getString("vehicle_ref") == vehicle && it.getBoolean("usable") }
                DeviceHealth.REGISTERED
            }
        }
        fun permitted(permission: String) = app.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
        val btAllowed = permitted(Manifest.permission.BLUETOOTH_CONNECT)
        val adapter = app.getSystemService(BluetoothManager::class.java).adapter
        val paired = if (btAllowed) adapter?.bondedDevices else null
        val system = if (btAllowed) app.getSystemService(CompanionDeviceManager::class.java).myAssociations else null
        val matches = if (system == null || local == null) null else
            system.any { it.id == local.companionId && it.deviceMacAddress?.toString().equals(local.address, true) } &&
                paired?.any { it.address.equals(local.address, true) } == true
        val name = paired?.find { it.address.equals(local?.address, true) }?.name
        val locationReady = permitted(Manifest.permission.ACCESS_FINE_LOCATION) &&
            permitted(Manifest.permission.ACCESS_BACKGROUND_LOCATION) &&
            app.getSystemService(LocationManager::class.java).isLocationEnabled
        val result = companionPresentation(device, local != null, binding, matches,
            if (btAllowed) adapter?.isEnabled else null, locationReady, app.store.homeCheck(owner).reason == null, name,
            // API 35 uses the enabled manifest receiver. API 36 has no existing persisted
            // proof that presence observation was started successfully: keep it unknown.
            observationVerified = Build.VERSION.SDK_INT == 35 &&
                app.resources.getBoolean(il.fca.companion.R.bool.acl_detector_enabled) &&
                app.packageManager.getComponentEnabledSetting(android.content.ComponentName(app,
                    il.fca.companion.detector.AclReceiver::class.java)) in setOf(
                        PackageManager.COMPONENT_ENABLED_STATE_DEFAULT, PackageManager.COMPONENT_ENABLED_STATE_ENABLED))
        if (current()) result else CompanionPresentation()
    } catch (_: Exception) { CompanionPresentation() }
}

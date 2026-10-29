package il.fca.companion.ui

import android.os.Bundle
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import java.security.MessageDigest

/** Task-scoped UI acknowledgement only. Never saves eligibility or server data. */
internal class FirstVehicleSetupState {
    private var restored = false
    private var key by mutableStateOf<String?>(null)
    private var handled by mutableStateOf(false)

    fun restoreOnce(bundle: Bundle?) {
        if (restored) return
        restored = true
        key = bundle?.getString("identity")
        handled = bundle?.getBoolean("handled", false) ?: false
    }
    fun save() = Bundle().apply {
        putString("identity", key)
        putBoolean("handled", handled)
    }
    private fun key(who: VehiclesIdentity) = MessageDigest.getInstance("SHA-256")
        .digest("${who.owner}\u0000${who.family}".toByteArray(Charsets.UTF_8))
        .joinToString("") { "%02x".format(it) }
    fun activate(who: VehiclesIdentity) {
        val next = key(who)
        if (key != next) { key = next; handled = false }
    }
    fun clear() { key = null; handled = false }
    fun needsCheck(who: VehiclesIdentity) = key == key(who) && !handled
    fun observe(who: VehiclesIdentity, vehicles: VehiclesState) {
        if (needsCheck(who) && vehicles.loaded && !vehicles.loading && !vehicles.loadError && vehicles.rows.isNotEmpty())
            handled = true
    }
    fun visible(who: VehiclesIdentity?, vehicles: VehiclesState): Boolean = who != null && needsCheck(who) &&
        vehicles.loaded && !vehicles.loading && !vehicles.loadError && vehicles.canCreate && vehicles.rows.isEmpty() &&
        vehicles.page == VehiclesPage.LIST
    fun dismiss(who: VehiclesIdentity): Boolean {
        if (!needsCheck(who)) return false
        handled = true
        return true
    }
}

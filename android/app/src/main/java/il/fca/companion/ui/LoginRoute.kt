package il.fca.companion.ui

import android.content.Context

enum class LoginRoute { CREATE_FAMILY, JOIN_FAMILY, EXISTING_ACCOUNT }

// Only the selected enum and expiry survive the external browser/process death.
// Forms, identity, error messages and resolution tokens are never saved here.
class PendingLoginRoute(context: Context) {
    private val preferences = context.getSharedPreferences("pending_login_route", Context.MODE_PRIVATE)
    fun save(route: LoginRoute, now: Long = System.currentTimeMillis()) {
        check(preferences.edit().putString("route", route.name).putLong("started", now).commit())
    }
    fun take(now: Long = System.currentTimeMillis()): LoginRoute? {
        val age = now - preferences.getLong("started", 0)
        val route = preferences.getString("route", null)
        clear()
        return if (age in 0..600_000) LoginRoute.entries.find { it.name == route } else null
    }
    fun clear() { preferences.edit().clear().apply() }
}

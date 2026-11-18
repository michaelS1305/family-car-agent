package il.fca.companion

import android.companion.CompanionDeviceManager
import il.fca.companion.data.LocalStore
import il.fca.companion.detector.DetectorPlatform
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ExecutionException
import java.util.concurrent.atomic.AtomicBoolean

/** Blocking refresh: call from an IO thread. No Activity is retained. */
object CompanionAccountRefresh {
    private val flights = ConcurrentHashMap<String, CompletableFuture<Unit>>()

    fun refresh(app: FcaApplication, owner: String) = refresh(app.store, owner, app.auth::owner,
        { path -> app.api.call(owner, path) },
        { id -> DetectorPlatform.stop(app.getSystemService(CompanionDeviceManager::class.java), id) })

    internal fun refresh(store: LocalStore, owner: String, authenticatedOwner: () -> String?,
                         request: (String) -> String, stopObservation: (Int) -> Unit) {
        val flight = CompletableFuture<Unit>()
        val existing = flights.putIfAbsent(owner, flight)
        if (existing != null) {
            try { existing.get() } catch (e: ExecutionException) { throw e.cause ?: e }
            return
        }
        val stale = AtomicBoolean(false)
        val listener: () -> Unit = { if (store.activeOwner() != owner) stale.set(true) }
        fun current() = !stale.get() && store.activeOwner() == owner && authenticatedOwner() == owner
        // The SQLite write lock also fences LocalStore.activate(). No HTTP is performed here.
        fun applyCurrent(action: () -> Unit) {
            val db = store.writableDatabase
            db.beginTransaction()
            try {
                if (current()) action()
            } finally {
                // This is an owner fence, not a new rollback policy: the old load()
                // retained a completed removal even when the following platform stop failed.
                try { db.setTransactionSuccessful() } finally { db.endTransaction() }
            }
        }
        LocalStore.listen(listener)
        try {
            if (current()) {
                val device = store.installation(owner).device
                if (device != null && current()) {
                    val devices = JSONArray(request("/api/devices"))
                    val registered = (0 until devices.length()).map { devices.getJSONObject(it) }
                        .find { it.getString("device_ref") == device }
                    check(registered != null && registered.isNull("revoked_at"))
                    if (current()) {
                        val bindings = JSONArray(request("/api/devices/$device/vehicle-bindings"))
                        val usable = (0 until bindings.length()).map { bindings.getJSONObject(it) }
                            .filter { it.getBoolean("usable") }.map { it.getString("vehicle_ref") }.toSet()
                        // Keep removal-before-stop ordering and propagate binding/observation failures.
                        applyCurrent {
                            store.associations(owner).filter { it.vehicle !in usable }.forEach {
                                store.remove(owner, it.vehicle)
                                stopObservation(it.companionId)
                            }
                        }
                        // As before, only RETURN home refresh failure clears the cache and is swallowed.
                        if (current()) runCatching {
                            val home = JSONObject(request("/api/devices/$device/return-home"))
                            applyCurrent { store.saveHome(owner, home.getDouble("latitude"), home.getDouble("longitude")) }
                        }.onFailure {
                            applyCurrent {
                                store.clearHome(owner)
                                store.diagnostic("return_home_refresh_failed")
                            }
                        }
                    }
                }
            }
            flight.complete(Unit)
        } catch (e: Throwable) {
            flight.completeExceptionally(e)
            throw e
        } finally {
            LocalStore.unlisten(listener)
            flights.remove(owner, flight)
        }
    }
}

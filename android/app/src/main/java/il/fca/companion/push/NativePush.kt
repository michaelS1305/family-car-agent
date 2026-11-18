package il.fca.companion.push

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageManager
import android.annotation.SuppressLint
import il.fca.companion.FcaApplication
import il.fca.companion.R
import il.fca.companion.ui.EntryActivity
import org.json.JSONObject


/** Default app process only; independent from Companion executors, tables and channels. */
class NativePush(private val app: FcaApplication) {
    private val manager get() = app.getSystemService(NotificationManager::class.java)
    private val engine: PushEngine? by lazy {
        if (!PushPlatform.enabled) null else runCatching {
            val storage = PushStorage(app)
            PushEngine(storage.read(), storage::write,
                identity = { app.store.activeOwner()?.takeIf { it == app.auth.owner() } },
                authOwner = { app.auth.owner() },
                call = { owner, path, method, body -> JSONObject(app.api.call(owner, path, method, body)) },
                token = PushPlatform::token, deleteToken = PushPlatform::deleteToken,
                display = ::display, clearNotifications = ::clearNotifications)
        }.getOrNull() // Unreadable private storage fails closed; never silently adopt another installation.
    }
    fun activate(owner: String, family: Long) {
        if (!PushPlatform.enabled) return
        runCatching {
            channel()
            engine?.activate(owner, family)
            PushWorker.enqueue(app)
        }
    }
    fun invalidate() {
        if (!PushPlatform.enabled) return
        try { runCatching { engine?.invalidate() } } finally {
            clearNotifications()
            PushWorker.enqueue(app) // Can revoke only while the SAME owner's existing auth is available.
        }
    }
    fun receive(data: Map<String, String>) {
        if (!PushPlatform.enabled) return
        runCatching { if (engine?.receive(data) == true) PushWorker.enqueue(app) }
    }
    /** Existing logout IO path only, before SessionStore clears the Bearer session.
     * Failure is not success: metadata remains for later SAME-owner reconciliation.
     */
    fun revokeAvailable() { if (PushPlatform.enabled) runCatching { engine?.reconcileRevocations() } }
    internal fun run(stopped: () -> Boolean) = runCatching { engine?.run(stopped) ?: true }.getOrDefault(true)
    private fun channel() {
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "עדכוני רכבים", NotificationManager.IMPORTANCE_DEFAULT))
    }
    private fun clearNotifications() {
        manager.activeNotifications.filter { it.tag?.startsWith(TAG) == true }.forEach { manager.cancel(it.tag, it.id) }
    }
    @SuppressLint("NotificationPermission")
    private fun display(event: PushEvent): Boolean {
        if (app.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            return false
        }

        channel()
        if (!pushNotificationsAllowed(
                app.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED,
                manager.areNotificationsEnabled(),
                manager.getNotificationChannel(CHANNEL)?.importance
            ))
            return false

        val intent = Intent(app, EntryActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)

        val tap = PendingIntent.getActivity(
            app, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        manager.notify(
            TAG + event.ref, 0,
            Notification.Builder(app, CHANNEL)
                .setSmallIcon(R.drawable.single_car_icon)
                .setContentTitle(app.getString(R.string.app_name))
                .setContentText(event.text())
                .setContentIntent(tap)
                .setAutoCancel(true)
                .setOnlyAlertOnce(true)
                .setVisibility(Notification.VISIBILITY_SECRET)
                .setTimeoutAfter((event.expires - System.currentTimeMillis()).coerceAtLeast(1))
                .build()
        )
        return true
    }

    companion object {
        const val CHANNEL = "fca_native_vehicle_events"
        private const val TAG = "fca-native:"
        val supported get() = PushPlatform.enabled
    }
}

internal fun pushNotificationsAllowed(permission: Boolean, enabled: Boolean, importance: Int?) =
    permission && enabled && importance != null && importance != NotificationManager.IMPORTANCE_NONE

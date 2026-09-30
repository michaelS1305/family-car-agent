package il.fca.companion.detector

import android.app.ForegroundServiceStartNotAllowedException
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import il.fca.companion.FcaApplication
import il.fca.companion.data.LocalStore
import il.fca.companion.data.ReturnCandidate
import il.fca.companion.delivery.DeliveryWorker
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

/** Online/above-ground experiment. No location is requested before persisted grace. */
class ReturnForegroundService : Service() {
    private val main = Handler(Looper.getMainLooper())
    private val destroyed = AtomicBoolean(false)
    private val version = AtomicLong()
    private var processedVersion = 0L // serial executor only
    private var lastStart = 0 // main thread only
    private var promoted = false
    private var controller: ReturnController? = null // serial executor only
    private var wake: PowerManager.WakeLock? = null // serial executor only, timeout is a final safety net
    private val stateListener: () -> Unit = { signal() }

    override fun onCreate() {
        super.onCreate()
        // Do not touch SQLite or wait on an executor before foreground promotion.
        try {
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel(CHANNEL, "FCA", NotificationManager.IMPORTANCE_LOW))
            val notification = Notification.Builder(this, CHANNEL)
                .setSmallIcon(android.R.drawable.ic_menu_mylocation)
                .setContentTitle("Family Car Agent").setContentText("מעדכן את מצב הרכב…")
                .setOngoing(true).setOnlyAlertOnce(true).build()
            startForeground(NOTIFICATION, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
            promoted = true
            LocalStore.listen(stateListener)
            serial.execute { log("return_fgs_started"); log("return_fgs_promoted") }
        } catch (error: Exception) {
            serial.execute { log("return_fgs_start_denied_${startFailure(error)}") }
            stopSelf()
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        lastStart = startId
        if (promoted) signal() else stopSelfResult(startId)
        return START_NOT_STICKY // Recovery uses durable state, never a replayed intent payload.
    }

    private fun signal() {
        val requested = version.incrementAndGet()
        serial.execute {
            if (!destroyed.get() && promoted) {
                processedVersion = requested
                guarded {
                    if (controller == null) controller = ReturnController(ports())
                    controller!!.refresh()
                }
            }
        }
    }

    private fun guarded(action: () -> Unit) {
        try { action() } catch (_: Exception) {
            runCatching { controller?.close() }
            controller = null
            release()
            log("return_fgs_stopped_internal_error")
            idle()
        }
    }

    private fun ports(): ReturnController.Ports {
        val store = (applicationContext as FcaApplication).store
        val execution = ReturnExecution(applicationContext, store) { DeliveryWorker.enqueue(applicationContext) }
        return object : ReturnController.Ports {
            override fun candidates() = store.activeOwner()?.let(store::candidates).orEmpty()
            override fun invalid(candidate: ReturnCandidate) = execution.invalid(candidate)
            override fun wall() = System.currentTimeMillis()
            override fun elapsed() = SystemClock.elapsedRealtime()
            override fun later(delay: Long, action: () -> Unit): ReturnController.Cancel {
                val future = serial.schedule({ if (!destroyed.get()) guarded(action) }, delay, TimeUnit.MILLISECONDS)
                return ReturnController.Cancel { future.cancel(false) }
            }
            override fun acquire(candidate: ReturnCandidate, complete: (ReturnWorker.LocationCheck) -> Unit): ReturnController.Cancel {
                val operation = execution.acquisition()
                val cancelled = AtomicBoolean(false)
                location.execute {
                    if (!cancelled.get() && !destroyed.get()) {
                        val result = try {
                            log("return_home_check_started")
                            val home = store.homeCheck(candidate.owner)
                            if (home.home == null) ReturnWorker.LocationCheck(reason = home.reason)
                            else {
                                val invalid = execution.invalid(candidate)
                                if (invalid != null) ReturnWorker.LocationCheck(reason = invalid)
                                else operation.acquire(true, true) // Permissions just checked; adapter rechecks fine permission too.
                            }
                        } catch (_: Exception) { ReturnWorker.LocationCheck(reason = "location_request_error") }
                        serial.execute { if (!destroyed.get()) guarded { complete(result) } }
                    }
                }
                return ReturnController.Cancel {
                    cancelled.set(true)
                    // CancellationSignal may wait on main-executor callbacks. Never
                    // block the controller/watchdog or service main thread on it.
                    cancellations.execute { operation.stop() }
                }
            }
            override fun decide(candidate: ReturnCandidate, result: ReturnWorker.LocationCheck) = execution.decide(candidate, result)
            override fun abandon(candidate: ReturnCandidate) = store.abandon(candidate)
            override fun awake(remaining: Long) {
                release()
                wake = getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,
                    "FCA:Return").apply { setReferenceCounted(false); acquire(remaining) }
            }
            override fun release() = this@ReturnForegroundService.release()
            override fun idle() = this@ReturnForegroundService.idle()
            override fun diagnostic(message: String) = log(message)
        }
    }

    private fun release() {
        wake?.let { runCatching { if (it.isHeld) it.release() } }
        wake = null
    }
    private fun idle() {
        val completedVersion = processedVersion
        main.post {
            // An older idle/completion cannot stop a newer onStartCommand or state signal.
            if (!destroyed.get() && version.get() == completedVersion && stopSelfResult(lastStart))
                stopForeground(STOP_FOREGROUND_REMOVE)
        }
    }
    private fun log(message: String) {
        runCatching { (applicationContext as FcaApplication).store.diagnostic(message) }
    }
    override fun onDestroy() {
        destroyed.set(true)
        LocalStore.unlisten(stateListener)
        stopForeground(STOP_FOREGROUND_REMOVE)
        serial.execute {
            try { controller?.close() } finally { release() }
        }
        super.onDestroy()
    }
    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        private const val CHANNEL = "fca_return"
        private const val NOTIFICATION = 4101
        // All services/recovery attempts share these executors in the app's sole process.
        private val serial = ScheduledThreadPoolExecutor(1).apply { removeOnCancelPolicy = true }
        private val location = Executors.newSingleThreadExecutor()
        private val cancellations = Executors.newFixedThreadPool(2)
        internal fun startFailure(error: Exception) = when (error) {
            is ForegroundServiceStartNotAllowedException -> "background_restricted"
            is SecurityException -> "permission"
            else -> "platform"
        }
        fun request(context: Context) {
            val app = context.applicationContext as FcaApplication
            serial.execute {
                fun log(value: String) = ReturnWorker.diagnostic(app.store::diagnostic, value)
                try {
                    val execution = ReturnExecution(app, app.store) {}
                    val candidates = app.store.activeOwner()?.let(app.store::candidates).orEmpty()
                    var eligible = false
                    for (candidate in candidates) {
                        val reason = execution.invalid(candidate)
                        if (reason != null) {
                            app.store.abandon(candidate)
                            log("return_fgs_start_denied_$reason")
                        } else if (ReturnController.remainingLifetime(candidate, System.currentTimeMillis(),
                                SystemClock.elapsedRealtime()) <= 0) {
                            app.store.abandon(candidate)
                            log("return_fgs_watchdog_expired")
                        } else eligible = true
                    }
                    if (eligible) {
                        log("return_fgs_start_requested")
                        app.startForegroundService(Intent(app, ReturnForegroundService::class.java))
                    }
                } catch (error: Exception) {
                    log("return_fgs_start_denied_${startFailure(error)}")
                }
            }
        }
    }
}

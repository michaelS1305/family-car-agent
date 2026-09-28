package il.fca.companion

import android.app.Application
import il.fca.companion.auth.SessionStore
import il.fca.companion.data.LocalStore
import il.fca.companion.delivery.DeliveryWorker
import il.fca.companion.net.FcaApi
import java.util.concurrent.Executors

class FcaApplication : Application() {
    val store by lazy { LocalStore(this) }
    val auth by lazy { SessionStore(this) }
    val api by lazy { FcaApi(auth) }
    val io = Executors.newSingleThreadExecutor()
    override fun onCreate() {
        super.onCreate()
        store.observeBoot(android.provider.Settings.Global.getInt(contentResolver, android.provider.Settings.Global.BOOT_COUNT, 0))
        DeliveryWorker.ensureRecovery(this)
        DeliveryWorker.enqueue(this)
    }
}

package il.fca.companion.push

import com.google.android.gms.tasks.Tasks
import com.google.firebase.FirebaseApp
import com.google.firebase.messaging.FirebaseMessaging
import il.fca.companion.BuildConfig
import java.util.concurrent.TimeUnit

internal object PushPlatform {
    const val enabled = true
    internal fun validIdentity(packageName: String, project: String?, sender: String?, app: String?): Boolean =
        packageName == "com.familycaragent.app" && project == "family-car-agent" &&
            sender == "249909620080" && app == "1:249909620080:android:c0f07c3b74400bfaee33b5"

    internal fun configured(): Boolean = runCatching {
        val app = FirebaseApp.getInstance()
        validIdentity(app.applicationContext.packageName, app.options.projectId,
            app.options.gcmSenderId, app.options.applicationId) &&
            BuildConfig.FCA_BASE_URL == "https://family-car-agent.onrender.com" &&
            BuildConfig.SUPABASE_URL == "https://xrgijytfigcuxmdktvmd.supabase.co"
    }.getOrDefault(false)

    private fun messaging(): FirebaseMessaging {
        check(configured()) { "Production Firebase configuration unavailable" }
        return FirebaseMessaging.getInstance()
    }
    fun token(): String = Tasks.await(messaging().token, 10, TimeUnit.SECONDS)
    fun deleteToken() { Tasks.await(messaging().deleteToken(), 10, TimeUnit.SECONDS) }
}

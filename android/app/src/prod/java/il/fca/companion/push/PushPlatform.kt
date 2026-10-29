package il.fca.companion.push

import com.google.android.gms.tasks.Tasks
import com.google.firebase.FirebaseApp
import com.google.firebase.messaging.FirebaseMessaging
import il.fca.companion.BuildConfig
import java.util.concurrent.TimeUnit

internal object PushPlatform {
    const val enabled = true
    internal fun validIdentity(packageName: String, project: String?, sender: String?, app: String?): Boolean =
        packageName == "il.fca.companion" && project == "family-car-agent-dev" &&
            sender == "452367109329" && app == "1:452367109329:android:c5a668180a0a8b84bdc9f0"

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

package il.fca.companion.push

import com.google.android.gms.tasks.Tasks
import com.google.firebase.FirebaseApp
import com.google.firebase.messaging.FirebaseMessaging
import java.util.concurrent.TimeUnit

internal object PushPlatform {
    const val enabled = true
    private fun messaging(): FirebaseMessaging {
        // Fail closed if the local build configuration is not the approved Dev project.
        check(FirebaseApp.getInstance().options.projectId == "family-car-agent-dev")
        return FirebaseMessaging.getInstance()
    }
    fun token(): String = Tasks.await(messaging().token, 10, TimeUnit.SECONDS)
    fun deleteToken() { Tasks.await(messaging().deleteToken(), 10, TimeUnit.SECONDS) }
}

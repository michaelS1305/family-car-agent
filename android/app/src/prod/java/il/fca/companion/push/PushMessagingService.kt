package il.fca.companion.push

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import il.fca.companion.FcaApplication

class PushMessagingService : FirebaseMessagingService() {
    override fun onNewToken(token: String) {
        if (PushPlatform.configured()) PushWorker.enqueue(this)
    }
    override fun onMessageReceived(message: RemoteMessage) {
        if (!PushPlatform.configured() || message.notification != null) return
        (application as FcaApplication).push.receive(message.data)
    }
}

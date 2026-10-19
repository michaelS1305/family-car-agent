package il.fca.companion.push

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import il.fca.companion.FcaApplication

class PushMessagingService : FirebaseMessagingService() {
    override fun onNewToken(token: String) {
        // Token stays in Firebase's own storage; never put it in WorkManager input/logs.
        PushWorker.enqueue(this)
    }
    override fun onMessageReceived(message: RemoteMessage) {
        if (message.notification != null) return // This protocol is data-only.
        (application as FcaApplication).push.receive(message.data)
    }
}

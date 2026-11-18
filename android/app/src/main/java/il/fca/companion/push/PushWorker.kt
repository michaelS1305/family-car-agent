package il.fca.companion.push

import android.content.Context
import androidx.work.*
import il.fca.companion.FcaApplication
import java.util.concurrent.TimeUnit

class PushWorker(context: Context, parameters: WorkerParameters) : Worker(context, parameters) {
    override fun doWork(): Result {
        if (!PushPlatform.enabled || isStopped) return Result.success()
        val complete = (applicationContext as FcaApplication).push.run { isStopped }
        return if (!complete && runAttemptCount < 2 && !isStopped) Result.retry() else Result.success()
    }
    companion object {
        fun enqueue(context: Context) {
            if (!PushPlatform.enabled) return
            WorkManager.getInstance(context).enqueueUniqueWork("fca-native-push", ExistingWorkPolicy.KEEP,
                OneTimeWorkRequestBuilder<PushWorker>()
                    .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                    .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
                    .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST).build())
        }
    }
}

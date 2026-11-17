package il.fca.companion.ui

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast

internal fun launchPublicLink(url: String, launch: (Intent) -> Unit): Boolean {
    if (url !in setOf(TERMS.url, PRIVACY.url, SUPPORT_URL, CONTACT_URL)) return false
    return try {
        launch(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        true
    } catch (_: ActivityNotFoundException) {
        false
    } catch (_: SecurityException) {
        false
    }
}

internal fun openPublicLink(context: Context, url: String) {
    if (!launchPublicLink(url) { context.startActivity(it) }) {
        Toast.makeText(context, "לא ניתן לפתוח את הקישור. יש לבדוק שמותקן דפדפן במכשיר.", Toast.LENGTH_LONG).show()
    }
}

package il.fca.companion.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
internal fun AccountDeletionDialog(model: AccountSettingsModel, logout: () -> Unit, logoutBusy: Boolean, logoutError: String?) {
    val state = model.state
    if (!state.dialog) return
    AlertDialog(onDismissRequest = model::dismiss,
        title = { Text("מחיקת חשבון") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("החשבון והמידע האישי שלכם ב־FCA יימחקו לצמיתות. לא ניתן לבטל את המחיקה.")
                Text("אם אתם מנהלי המשפחה ונשארו חברים נוספים, הניהול יועבר לחבר אחר. אם אתם החברים האחרונים, גם המשפחה והמידע המשפחתי יימחקו.")
                when (state.consequence) {
                    "management_transferred" -> Text("במצב הנוכחי, ניהול המשפחה יועבר לחבר אחר.")
                    "family_deleted" -> Text("אתם החברים האחרונים: גם המשפחה והמידע שלה יימחקו.")
                }
                if (state.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
                when (state.phase) {
                    "draining", "auth_pending" -> Text("הבקשה התקבלה והחשבון חסום לפעילות. המחיקה תימשך בשרת גם לאחר ההתנתקות.")
                    "completed" -> Text("החשבון נמחק.")
                }
                if (state.uncertain) Text("ייתכן שהמחיקה כבר החלה. אין לשלוח בקשה נוספת. בדקו את המצב או סגרו והתנתקו.")
                (state.error ?: logoutError)?.let { Text(it) }
            }
        },
        confirmButton = {
            if (state.consequence != null && !state.protected) {
                TextButton(model::confirm, enabled = !state.busy && !logoutBusy) { Text("אני מאשר/ת מחיקה לצמיתות") }
            } else {
                TextButton(model::checkStatus, enabled = !state.busy && !logoutBusy) { Text("בדיקת מצב") }
            }
        },
        dismissButton = {
            if (state.protected || state.error != null) {
                TextButton(logout, enabled = !state.busy && !logoutBusy) { Text("סגירה והתנתקות") }
            } else {
                TextButton(model::dismiss, enabled = !state.busy) { Text("ביטול") }
            }
        })
}

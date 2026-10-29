package il.fca.companion.ui

import android.content.Intent

// Replace only when an official, environment-appropriate public link is approved.
internal const val FAMILY_INVITATION_APP_LINK = "[קישור לאפליקציה — יתווסף בקרוב]"

internal fun familyInvitationChooser(code: String): Intent {
    require(code.matches(Regex("[a-z0-9]{6}")))
    val message = """
        היי! 👋

        רוצה להצטרף למשפחה שלנו ב־Family Car Agent? 🚗

        תקבל סוכן חכם אישי שיעזור לך לנהל את הרכבים המשפחתיים, לעקוב אחרי השימוש בהם ולתאם נסיעות בקלות.

        📲 להצטרפות לאפליקציה:
        $FAMILY_INVITATION_APP_LINK

        🔑 הקוד המשפחתי שלנו:
        $code

        🔒 חשוב: הקוד המשפחתי מיועד לבני המשפחה בלבד. נא לשמור עליו ולא להעביר אותו לאנשים מחוץ למשפחה.
    """.trimIndent()
    return Intent.createChooser(Intent(Intent.ACTION_SEND).apply {
        type = "text/plain"
        putExtra(Intent.EXTRA_TEXT, message)
    }, "הזמנת בן משפחה")
}

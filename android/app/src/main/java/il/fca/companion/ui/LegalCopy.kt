package il.fca.companion.ui

// Canonical destinations for the finalized v1.2 documents. Website deployment is separate.
internal class LegalCopy(val title: String, val url: String)
internal val TERMS = LegalCopy("תנאי שימוש", "https://familycaragent.com/terms")
internal val PRIVACY = LegalCopy("מדיניות פרטיות", "https://familycaragent.com/privacy")
internal const val SUPPORT_URL = "https://familycaragent.com/support"
internal const val CONTACT_URL = "https://familycaragent.com/contact"
internal const val LEGAL_CONSENT = "קראתי ואני מסכים/ה לתנאי השימוש, ואני מאשר/ת שקראתי את מדיניות הפרטיות של Family Car Agent."
internal const val LEGAL_CONSENT_REQUIRED = "כדי להשלים את ההרשמה, יש להסכים לתנאי השימוש ולאשר שקראת את מדיניות הפרטיות."

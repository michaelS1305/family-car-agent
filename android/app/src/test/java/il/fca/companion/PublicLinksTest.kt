package il.fca.companion

import android.app.Application
import android.content.ActivityNotFoundException
import android.content.Intent
import androidx.compose.ui.text.LinkAnnotation
import il.fca.companion.ui.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class PublicLinksTest {
    @Test fun canonicalDestinationsUseBrowserIntentsWithoutPrivateData() {
        val urls = listOf(TERMS.url, PRIVACY.url, SUPPORT_URL, CONTACT_URL)
        assertEquals(listOf("terms", "privacy", "support", "contact").map { "https://familycaragent.com/$it" }, urls)
        urls.forEach { url ->
            var intent: Intent? = null
            assertTrue(launchPublicLink(url) { intent = it })
            assertEquals(Intent.ACTION_VIEW, intent!!.action)
            assertEquals(url, intent!!.dataString)
            assertNull(intent!!.extras)
        }
    }
    @Test fun missingBrowserAndBlockedActivityFailSafely() {
        assertFalse(launchPublicLink(TERMS.url) { throw ActivityNotFoundException() })
        assertFalse(launchPublicLink(PRIVACY.url) { throw SecurityException() })
        assertFalse(launchPublicLink("https://unrelated.example") { fail("Must not launch") })
    }
    @Test fun loginAndOnboardingEachOpenBothFullDocumentsWithoutChangingConsent() {
        val opened = mutableListOf<String>()
        val onboarding = onboardingLegalText { opened += it.url }
        assertEquals(LEGAL_CONSENT, onboarding.text)
        for (text in listOf(loginLegalText { opened += it.url }, onboarding)) {
            val links = text.getLinkAnnotations(0, text.length)
            assertEquals(2, links.size)
            links.forEach { range ->
                val link = range.item as LinkAnnotation.Clickable
                link.linkInteractionListener!!.onClick(link)
            }
        }
        assertEquals(listOf(PRIVACY.url, TERMS.url, TERMS.url, PRIVACY.url), opened)
    }
}

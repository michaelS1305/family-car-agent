package il.fca.companion

import android.app.Application
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.font.createFontFamilyResolver
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.LayoutDirection
import il.fca.companion.ui.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class GoogleLoginLayoutTest {
    @Test fun completeCardFitsRepresentativeUsablePhoneViewports() {
        for (width in listOf(320, 360, 393, 412, 480)) for (height in listOf(560, 640, 740, 860)) {
            val density = Density(1f)
            val measurer = TextMeasurer(createFontFamilyResolver(RuntimeEnvironment.getApplication()), density, LayoutDirection.Rtl)
            val layout = loginLayout(measurer, density, minOf(width - 32f, 440f) - 32f, height - 64f, loginLegalText {})
            assertTrue("$width x $height: ${layout.cardHeight}", layout.cardHeight <= height - 64f)
            assertTrue(layout.gap >= 0f)
            assertTrue(layout.secondary.fontSize.value >= 11f)
            assertTrue(layout.secondary.fontSize.value < layout.subtitle.fontSize.value)
            assertTrue(layout.legalStyle.fontSize.value < layout.subtitle.fontSize.value)
            assertTrue(layout.authGap <= 10f)
            assertTrue(layout.legalGap <= 6f)
        }
    }

    @Test fun approvedCopyAndBothLegalLinksRemainExact() {
        assertEquals("מתחברים וממשיכים", LOGIN_TITLE)
        assertEquals("כדי להשלים את החיבור והזיהוי שלכם, התחברו עם חשבונכם האישי", LOGIN_SUBTITLE)
        assertEquals("פרטי ההתחברות נשמרים ומנוהלים על ידי Supabase Auth.", LOGIN_AUTH_NOTE)
        val legal = loginLegalText {}
        assertEquals("אנו מעבדים מידע אישי כדי לספק את Family Car Agent. מידע על המטרות, הספקים והזכויות שלך מופיע ב־ מדיניות הפרטיות וב־תנאי השימוש.", legal.text)
        val links = legal.getLinkAnnotations(0, legal.length)
        assertEquals(listOf("מדיניות הפרטיות", "תנאי השימוש"), links.map { legal.text.substring(it.start, it.end) })
    }
}

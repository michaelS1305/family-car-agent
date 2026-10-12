package il.fca.companion

import android.app.Application
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.sp
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.font.createFontFamilyResolver
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.LayoutDirection
import il.fca.companion.ui.INTRO_HERO
import il.fca.companion.ui.INTRO_BODY
import il.fca.companion.ui.introTextStyle
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
class IntroLayoutTest {
    @Test fun contentFitsShortNormalAndTallUsableViewports() {
        for (width in listOf(320, 360, 393, 412, 480)) for (height in listOf(480, 560, 680, 820)) {
            for (scale in listOf(1f, 1.3f, 1.5f)) {
                val measurer = TextMeasurer(createFontFamilyResolver(RuntimeEnvironment.getApplication()), Density(1f, scale), LayoutDirection.Rtl)
                val available = minOf(width, 440) - 32
                val compact = height < 560
                fun measured(text: String, preferred: Float, target: Int = available): Int =
                    measurer.measure(text, introTextStyle(measurer, text, target, preferred, FontWeight.Bold), softWrap = false).size.height
                val bodyHeight = measurer.measure(INTRO_BODY, TextStyle(fontFamily = FontFamily.SansSerif,
                    fontSize = (if (compact) 15 else 16).sp, lineHeight = (if (compact) 22 else 25).sp,
                    fontWeight = FontWeight.Medium), constraints = Constraints(maxWidth = available)).size.height
                val fixed = (if (compact) 96 else 126) + 2 + measured("Family Car Agent", if (compact) 30f else 34f) +
                    measured(INTRO_HERO, if (compact) 26f else 29f) + bodyHeight +
                    maxOf(60, measured("הצטרפות\nלמשפחה", 16f, (available - 10) / 2 - 44) + 16) +
                    maxOf(48, measured("כבר יש לי חשבון", 15f, available - 32) + 16)
                assertTrue("Content $fixed exceeds $width x $height at font scale $scale", fixed < height)
            }
        }
    }
    @Test fun explicitLinesFitActualFontMetricsAcrossPhoneWidthsAndFontScales() {
        for (width in listOf(320, 360, 393, 412, 480)) for (scale in listOf(1f, 1.3f, 1.5f)) {
            val measurer = TextMeasurer(createFontFamilyResolver(RuntimeEnvironment.getApplication()), Density(1f, scale), LayoutDirection.Rtl)
            val contentWidth = minOf(width, 440) - 32
            val labelWidth = (contentWidth - 10) / 2 - 44
            for ((text, available, preferred) in listOf(Triple(INTRO_HERO, contentWidth, 29f),
                Triple("Family Car Agent", contentWidth, 34f), Triple("הצטרפות\nלמשפחה", labelWidth, 16f),
                Triple("יצירת\nמשפחה", labelWidth, 16f))) {
                val style = introTextStyle(measurer, text, available, preferred, FontWeight.Bold)
                val result = measurer.measure(text, style, softWrap = false)
                assertTrue("$width/$scale: $text", result.size.width <= available)
                assertEquals(if (text.contains('\n')) 2 else 1, result.lineCount)
                assertFalse(result.hasVisualOverflow)
            }
        }
    }
}

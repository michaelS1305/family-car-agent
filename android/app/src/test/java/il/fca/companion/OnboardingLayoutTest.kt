package il.fca.companion

import android.app.Application
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.font.createFontFamilyResolver
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.sp
import il.fca.companion.ui.DRIVING_CONSENT
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
class OnboardingLayoutTest {
    private fun contentHeights(width: Int, height: Int): List<Int> {
        val measure = TextMeasurer(createFontFamilyResolver(RuntimeEnvironment.getApplication()), Density(1f), LayoutDirection.Rtl)
        val content = minOf(width, 440) - 32
        val compact = height < 620
        fun text(value: String, size: Int, line: Int, available: Int = content, bold: Boolean = false) =
            measure.measure(value, TextStyle(fontSize = size.sp, lineHeight = line.sp,
                fontWeight = if (bold) FontWeight.Bold else FontWeight.Normal),
                constraints = Constraints(maxWidth = available)).size.height
        fun title(value: String) = text(value, 30, 38, bold = true)
        val field = text("שם המשפחה", 16, 24, bold = true) + 7 + 56
        val base = 24 + 48 + (if (compact) 12 else 48) + 54
        return listOf(
            base + title("איך קוראים למשפחה?") + (if (compact) 24 else 52) + field,
            base + title("מה כתובת הבית?") + (if (compact) 10 else 16) +
                text("הכתובת נדרשת לאימות המשפחה ולבדיקת ניתוק הרכב האופציונלית בקרבת הבית.", 14, 21) +
                (if (compact) 16 else 30) + field + 8 +
                text("יש להזין את הכתובת כפי שהיא מופיעה ב-Google Maps.\nיש לכתוב: עיר, רחוב, מספר בית.", 13, 19),
            base - (if (compact) 0 else 24) + title("זו הכתובת הנכונה?") + 10 +
                text("בדקו את הפרטים לפני שממשיכים.", 14, 21) + (if (compact) 12 else 20) +
                text("רחוב לדוגמה 120, תל אביב, ישראל", 16, 24, content - 24, true) + 24 + 10 +
                (if (compact) 72 else 100) + 10 + 50,
            base + title("קוד המשפחה") + (if (compact) 24 else 46) + field + 12 +
                text("שימו לב, יש מספר ניסיונות מוגבל", 13, 19),
            base + title("איך קוראים לך?") + (if (compact) 16 else 24) + field + 10 +
                maxOf(48, text(DRIVING_CONSENT, 11, 15, content - 8 - 48 - 4) + 8) + 8
        )
    }

    @Test fun allFiveStepsFitRepresentativePhoneViewports() {
        for (width in listOf(320, 360, 393, 412, 480)) for (height in listOf(560, 640, 740, 860)) {
            contentHeights(width, height).forEachIndexed { index, needed ->
                assertTrue("Step ${index + 1}: $needed exceeds $width x $height", needed <= height)
            }
        }
    }

    @Test fun keyboardSizedViewportCannotContainAllConsentContentAndControls() {
        // Documents the physical lower bound; do not hide consent or reduce touch targets to meet it.
        assertTrue(contentHeights(360, 320).last() > 320)
    }
}

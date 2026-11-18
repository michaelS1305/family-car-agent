package il.fca.companion

import android.app.Application
import android.graphics.Color
import android.graphics.drawable.AdaptiveIconDrawable
import android.graphics.drawable.InsetDrawable
import android.graphics.drawable.VectorDrawable
import android.graphics.drawable.BitmapDrawable
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class LaunchBrandingTest {
    @Test fun launcherUsesApprovedBitmapAndSplashKeepsOriginalVector() {
        val context = RuntimeEnvironment.getApplication()
        val icon = context.getDrawable(R.mipmap.ic_launcher) as AdaptiveIconDrawable
        assertTrue((icon.foreground as InsetDrawable).drawable is BitmapDrawable)
        assertTrue((context.getDrawable(R.drawable.fca_splash_icon) as InsetDrawable).drawable is VectorDrawable)
        assertEquals(Color.rgb(246, 247, 247), context.getColor(R.color.fca_launch_background))
        assertNull(icon.monochrome)
    }

    @Test fun navyArtworkIsProminentAndInsideAdaptiveSafeCircle() {
        val context = RuntimeEnvironment.getApplication()
        val foreground = (context.getDrawable(R.mipmap.ic_launcher) as AdaptiveIconDrawable).foreground as InsetDrawable
        foreground.setBounds(0, 0, 1000, 1000)
        val bitmap = (foreground.drawable as BitmapDrawable).bitmap
        assertEquals(bitmap.width, bitmap.height)
        assertEquals(80, foreground.drawable!!.bounds.left)
        assertEquals(920, foreground.drawable!!.bounds.right)
        var radius = 0.0
        var count = 0
        for (y in 0 until bitmap.height) for (x in 0 until bitmap.width) {
            val pixel = bitmap.getPixel(x, y)
            val brightest = maxOf(Color.red(pixel), Color.green(pixel), Color.blue(pixel))
            if (Color.alpha(pixel) > 240 && brightest in 6..99) {
                val dx = (x - bitmap.width / 2.0) / bitmap.width * 108 * .84
                val dy = (y - bitmap.height / 2.0) / bitmap.height * 108 * .84
                radius = maxOf(radius, kotlin.math.sqrt(dx * dx + dy * dy))
                count++
            }
        }
        assertTrue(count > 10000)
        assertTrue("Logo should fill the safe area without clipping: $radius", radius in 27.0..33.0)
    }

    @Test fun entryThemeUsesStaticPlatformSplashWithoutDurationOverride() {
        val context = RuntimeEnvironment.getApplication()
        val theme = context.resources.newTheme().apply { applyStyle(R.style.Theme_Fca_Entry, true) }
        val attrs = theme.obtainStyledAttributes(intArrayOf(
            android.R.attr.windowSplashScreenBackground,
            android.R.attr.windowSplashScreenAnimatedIcon,
            android.R.attr.windowSplashScreenBehavior))
        try {
            assertEquals(Color.rgb(246, 247, 247), attrs.getColor(0, 0))
            assertEquals(R.drawable.fca_splash_icon, attrs.getResourceId(1, 0))
            assertEquals(1, attrs.getInt(2, 0))
        } finally { attrs.recycle() }
    }
}

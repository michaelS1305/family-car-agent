package il.fca.companion

import android.app.Application
import android.graphics.Color
import android.graphics.drawable.AdaptiveIconDrawable
import android.graphics.drawable.InsetDrawable
import android.graphics.drawable.VectorDrawable
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class LaunchBrandingTest {
    @Test fun launcherAndSplashInflateUsingOriginalVector() {
        val context = RuntimeEnvironment.getApplication()
        val icon = context.getDrawable(R.mipmap.ic_launcher) as AdaptiveIconDrawable
        assertTrue((icon.foreground as InsetDrawable).drawable is VectorDrawable)
        assertTrue((context.getDrawable(R.drawable.fca_splash_icon) as InsetDrawable).drawable is VectorDrawable)
        assertEquals(Color.rgb(246, 247, 247), context.getColor(R.color.fca_launch_background))
        assertNull(icon.monochrome)
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

package il.fca.companion

import android.app.Application
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.view.View
import java.io.File
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
class WordmarkTest {
    private fun render(direction: Int): Bitmap {
        val drawable = checkNotNull(RuntimeEnvironment.getApplication().getDrawable(R.drawable.family_car_agent_road_logo_1__dark))
        assertFalse("English branding must never mirror", drawable.isAutoMirrored)
        drawable.layoutDirection = direction
        return Bitmap.createBitmap(434, 145, Bitmap.Config.ARGB_8888).also {
            drawable.setBounds(0, 0, it.width, it.height)
            drawable.draw(Canvas(it))
        }
    }

    @Test fun approvedVectorHasTransparentExteriorAndVisibleArtworkWithoutRtlMirroring() {
        val ltr = render(View.LAYOUT_DIRECTION_LTR)
        val rtl = render(View.LAYOUT_DIRECTION_RTL)
        assertTrue(ltr.sameAs(rtl))
        var visible = 0
        for (y in 0 until ltr.height) for (x in 0 until ltr.width) {
            val alpha = Color.alpha(ltr.getPixel(x, y))
            if (x == 0 || y == 0 || x == ltr.width - 1 || y == ltr.height - 1) assertEquals(0, alpha)
            if (alpha > 0) visible++
        }
        assertTrue("Logo must actually draw", visible > 100)
        assertTrue("No filled rectangular background", visible < ltr.width * ltr.height / 2)
        ltr.recycle(); rtl.recycle()
    }

    @Test fun everyHeaderSelectsApprovedAssetFromFcaThemeAndPreservesLightBlending() {
        val directory = File("src/main/java/il/fca/companion/ui")
        val files = directory.listFiles()!!.filter { it.extension == "kt" && it.readText().contains("R.drawable.fca_header_wordmark") }
        assertEquals(8, files.size)
        files.forEach {
            val source = it.readText()
            assertTrue(it.name, source.contains("if (LocalFcaDark.current) R.drawable.family_car_agent_road_logo_1__dark else R.drawable.fca_header_wordmark"))
            assertTrue(it.name, source.contains("if (LocalFcaDark.current) BlendMode.SrcOver else BlendMode.Multiply"))
        }
    }
}

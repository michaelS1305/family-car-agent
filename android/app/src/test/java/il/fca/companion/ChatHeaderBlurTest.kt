package il.fca.companion

import android.app.Application
import android.graphics.RenderEffect
import android.graphics.RuntimeShader
import org.junit.Assert.assertNotNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class ChatHeaderBlurTest {
    @Test fun productionShaderCompilesAndBothPassesAcceptTheirUniforms() {
        // Read the actual private production shader, not a duplicated test fixture.
        val field = Class.forName("il.fca.companion.ui.ChatScreenKt")
            .getDeclaredField("HeaderBlurShader").apply { isAccessible = true }
        val source = field.get(null) as String
        fun pass(x: Float, y: Float): RenderEffect {
            val shader = RuntimeShader(source).apply {
                setFloatUniform("headerHeight", 120f)
                setFloatUniform("maxRadius", 16f)
                setFloatUniform("direction", x, y)
            }
            return RenderEffect.createRuntimeShaderEffect(shader, "content")
        }
        assertNotNull(RenderEffect.createChainEffect(pass(0f, 1f), pass(1f, 0f)))
    }
}

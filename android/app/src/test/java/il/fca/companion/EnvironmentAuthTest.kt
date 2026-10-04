package il.fca.companion

import android.app.Application
import android.content.Intent
import android.net.Uri
import il.fca.companion.auth.SessionStore
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class EnvironmentAuthTest {
    @Test fun callbackConstructionUsesSelectedEnvironmentAndEscapesNonce() {
        val uri = SessionStore.callbackUri("fixture & nonce")
        assertEquals(Uri.parse(BuildConfig.OAUTH_CALLBACK_URI).scheme, uri.scheme)
        assertEquals("auth", uri.host)
        assertEquals("/callback", uri.path)
        assertEquals("fixture & nonce", uri.getQueryParameter("nonce"))
    }
    @Test fun selectedFlavorHasExactIdentityEndpointsAndManifest() {
        val dev = BuildConfig.FLAVOR == "dev"
        val id = if (dev) "il.fca.companion.dev" else "il.fca.companion"
        assertEquals(id, BuildConfig.APPLICATION_ID)
        assertEquals(if (dev) "https://family-car-agent-dev.onrender.com" else
            "https://family-car-agent.onrender.com", BuildConfig.FCA_BASE_URL)
        assertEquals(if (dev) "https://jouhqvbxhsvkluwkqmdg.supabase.co" else
            "https://xrgijytfigcuxmdktvmd.supabase.co", BuildConfig.SUPABASE_URL)
        assertEquals("$id://auth/callback", BuildConfig.OAUTH_CALLBACK_URI)
        val context = RuntimeEnvironment.getApplication()
        assertEquals(if (dev) "FCA Companion Dev" else "FCA Companion", context.getString(R.string.app_name))
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(BuildConfig.OAUTH_CALLBACK_URI))
            .addCategory(Intent.CATEGORY_BROWSABLE).addCategory(Intent.CATEGORY_DEFAULT)
            .setPackage(BuildConfig.APPLICATION_ID)
        assertFalse(context.packageManager.queryIntentActivities(intent, 0).isEmpty())
    }

    @Test fun callbackForOtherEnvironmentRejectedBeforeSessionOrNetworkAccess() {
        val context = RuntimeEnvironment.getApplication()
        val other = if (BuildConfig.FLAVOR == "dev") "il.fca.companion" else "il.fca.companion.dev"
        val failure = runCatching {
            SessionStore(context).finishLogin(Uri.parse("$other://auth/callback?code=unused&nonce=unused"))
        }.exceptionOrNull()
        assertTrue(failure is IllegalArgumentException)
    }
}

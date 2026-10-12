package il.fca.companion

import android.app.Application
import il.fca.companion.net.OnboardingFailure
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.ByteArrayInputStream
import java.io.InputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class OnboardingFailureTest {
    @Test fun missingAccountRequiresExactStatusPathAndMessage() {
        for (message in listOf("Authenticated user is not registered in the application",
            "Authenticated user is not assigned to a family")) {
            val body = """{"detail":"$message"}"""
            assertTrue(OnboardingFailure.parse(403, "/api/me", body).missingAccount)
            assertFalse(OnboardingFailure.parse(401, "/api/me", body).missingAccount)
            assertFalse(OnboardingFailure.parse(403, "/api/onboarding/join-family/start", body).missingAccount)
            assertFalse(OnboardingFailure.parse(403, "/api/me", """{"detail":"$message!"}""").missingAccount)
        }
        assertFalse(OnboardingFailure.parse(403, "/api/me", """{"detail":"Forbidden"}""").missingAccount)
    }
    @Test fun typedJoinFieldsRemainUiOnly() {
        val error = OnboardingFailure.parse(429, "/api/onboarding/join-family/code", """
            {"detail":{"code":"JOIN_LOCKED","message":"נותר ניסיון אחרון",
            "attempts_remaining":0,"locked_until":"2026-10-06T12:00:00+00:00",
            "retry_after_seconds":900,"token":"never retained"}}
        """)
        assertEquals("JOIN_LOCKED", error.code)
        assertEquals("נותר ניסיון אחרון", error.uiMessage)
        assertEquals(0, error.attemptsRemaining)
        assertEquals(900, error.retryAfterSeconds)
        assertEquals("2026-10-06T12:00:00+00:00", error.lockedUntil)
        assertEquals("HTTP 429", error.message)
        assertNull(error.cause)
        assertFalse(error.toString().contains("נותר"))
    }
    @Test fun malformedFieldsAndBodiesFailClosed() {
        for (body in listOf("", "[]", "not json", "{}", """{"detail":[]}""",
            """{"detail":{"message":[],"code":{},"attempts_remaining":-1,"locked_until":"bad","retry_after_seconds":"900"}}""")) {
            val error = OnboardingFailure.parse(503, "/api/onboarding/join-family/code", body)
            assertEquals(503, error.status)
            assertFalse(error.missingAccount)
            assertNull(error.uiMessage)
            assertNull(error.code)
            assertNull(error.lockedUntil)
            assertNull(error.attemptsRemaining)
            assertNull(error.retryAfterSeconds)
        }
    }
    @Test fun parsedPathCannotBeUsedForDeliveryOrArbitraryApis() {
        assertFalse(OnboardingFailure.supports("/api/devices/device/events/take", "POST"))
        assertFalse(OnboardingFailure.supports("/api/devices/device/events/return", "POST"))
        assertFalse(OnboardingFailure.supports("/api/family", "GET"))
        assertFalse(OnboardingFailure.supports("/api/me", "POST"))
        assertTrue(OnboardingFailure.supports("/api/me", "GET"))
    }
    @Test fun oversizeOrBrokenStreamPreservesGenericStatusWithoutBodyOrCause() {
        val streams = listOf(null, ByteArrayInputStream(ByteArray(8193)),
            object : InputStream() { override fun read(): Int = throw IOException("private fixture") })
        for (stream in streams) {
            val connection = object : HttpURLConnection(URL("https://example.invalid")) {
                override fun getErrorStream() = stream
                override fun connect() = Unit
                override fun disconnect() = Unit
                override fun usingProxy() = false
            }
            val error = OnboardingFailure.read(connection, 503, "/api/onboarding/join-family/code")
            assertEquals("HTTP 503", error.message)
            assertNull(error.uiMessage); assertNull(error.cause); assertNull(error.code)
        }
    }
}

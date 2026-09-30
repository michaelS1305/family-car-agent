package il.fca.companion

import android.app.Application
import il.fca.companion.net.Http
import il.fca.companion.net.HttpFailure
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.ByteArrayInputStream
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class HttpDiagnosticsTest {
    private fun connection(stream: InputStream?) = object : HttpURLConnection(URL("https://example.invalid")) {
        override fun getErrorStream() = stream
        override fun connect() {}
        override fun disconnect() {}
        override fun usingProxy() = false
    }
    private fun failure(body: String, status: Int = 404) =
        Http.failure(connection(ByteArrayInputStream(body.toByteArray())), status)

    @Test fun extractsOnlyExplicitlyAllowedCodes() {
        for (code in listOf("DEVICE_NOT_FOUND_OR_UNAVAILABLE", "VEHICLE_NOT_FOUND_OR_UNAVAILABLE",
                "DEVICE_OR_VEHICLE_UNAVAILABLE")) {
            val error = failure("""{"detail":{"code":"$code","message":"secret coordinates token"}}""")
            assertEquals(code, error.diagnosticCode)
            assertEquals("HTTP 404", error.message)
            assertNull(error.cause)
        }
    }
    @Test fun distinguishesPlainRouteNotFound() {
        assertEquals("route_not_found", failure("""{"detail":"Not Found"}""").diagnosticCode)
    }
    @Test fun unexpectedMalformedAndOversizeBodiesFallBack() {
        for (body in listOf("", "not json", "[]", "{}", """{"detail":null}""",
                """{"detail":{"code":["DEVICE_NOT_FOUND_OR_UNAVAILABLE"]}}""",
                """{"detail":{"code":"secret-token"}}""", """{"detail":"Not Found secret"}""",
                " ".repeat(4097))) {
            assertNull(failure(body).diagnosticCode)
        }
    }
    @Test fun missingOrFailingStreamCannotReplaceOriginalHttpFailure() {
        assertNull(Http.failure(connection(null), 503).diagnosticCode)
        val stream = object : InputStream() { override fun read(): Int = throw IOException("private data") }
        val error = Http.failure(connection(stream), 404)
        assertEquals(404, error.status)
        assertNull(error.diagnosticCode)
        assertNull(error.cause)
        assertEquals("HTTP 404", error.message)
    }
    @Test fun diagnosticMetadataPreservesStatusAndExistingExceptionContract() {
        // FcaApi's refresh decision remains status == 401; DeliveryWorker still
        // catches HttpFailure and returns retry without acknowledging the head.
        for (status in listOf(401, 404, 429, 503)) {
            val error = failure("""{"detail":"Not Found"}""", status)
            assertEquals(status, error.status)
            assertTrue(error is IOException)
            assertEquals(HttpFailure(status).message, error.message)
        }
    }
}

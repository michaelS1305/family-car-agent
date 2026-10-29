package il.fca.companion

import android.app.Application
import il.fca.companion.net.*
import java.net.SocketTimeoutException
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class BootstrapReadTest {
    @Test fun transientReadRecoversWithBoundedBackoff() = runBlocking {
        var calls = 0
        val delays = mutableListOf<Long>()
        assertEquals("ready", BootstrapRead.run({ true }, { delays += it }) {
            calls++
            if (calls < 3) throw SocketTimeoutException()
            "ready"
        })
        assertEquals(3, calls)
        assertEquals(listOf(1000L, 2000L), delays)
    }
    @Test fun unavailableBackendStopsAfterThreeReads() = runBlocking {
        var calls = 0
        val failure = OnboardingFailure.parse(503, "/api/me", "{}")
        val result = runCatching { BootstrapRead.run({ true }, {}) { calls++; throw failure } }
        assertSame(failure, result.exceptionOrNull())
        assertEquals(3, calls)
    }
    @Test fun authValidationRateLimitsAndUnknownIoAreNotRetried() = runBlocking {
        val failures = listOf(401,403,404,409,429,500).map { OnboardingFailure.parse(it,"/api/me","{}") } +
            listOf(java.io.IOException(), IllegalArgumentException(), CancellationException())
        for (failure in failures) {
            var calls = 0
            val result = runCatching { BootstrapRead.run({ true }, { fail("Unexpected retry") }) { calls++; throw failure } }
            assertSame(failure, result.exceptionOrNull()); assertEquals(1, calls)
        }
    }
    @Test fun identityChangeDuringBackoffPreventsAnotherRequest() = runBlocking {
        var current = true; var calls = 0
        val result = runCatching { BootstrapRead.run({ current }, { current = false }) { calls++; throw SocketTimeoutException() } }
        assertTrue(result.isFailure); assertEquals(1, calls)
    }
    @Test fun cancellationDuringBackoffStopsAndLateSuccessIsFenced() = runBlocking {
        var calls = 0
        val job = launch {
            BootstrapRead.run({ true }, { awaitCancellation() }) { calls++; throw SocketTimeoutException() }
        }
        yield(); job.cancelAndJoin(); assertEquals(1, calls)
        var current = true
        assertTrue(runCatching { BootstrapRead.run({ current }) { current = false; "old" } }.isFailure)
    }
}

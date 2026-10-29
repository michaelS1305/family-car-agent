package il.fca.companion

import il.fca.companion.ui.MapLoadAttempt
import il.fca.companion.ui.MapLoadPhase
import org.junit.Assert.*
import org.junit.Test

class MapLoadAttemptTest {
    @Test fun successCannotBecomeTimeout() {
        val state = MapLoadAttempt(); state.loaded(); state.timeout()
        assertEquals(MapLoadPhase.LOADED, state.phase)
        assertFalse(state.retry())
    }
    @Test fun slowLoadRecoversOnSameAttemptWhenConnectivityReturns() {
        val state = MapLoadAttempt(); state.timeout()
        assertEquals(MapLoadPhase.SLOW, state.phase)
        state.loaded(); assertEquals(MapLoadPhase.LOADED, state.phase)
    }
    @Test fun initializationFailureRequiresExplicitRateLimitedRetry() {
        val state = MapLoadAttempt(); state.failed()
        assertFalse(state.retry()); state.allowRetry()
        assertTrue(state.retry()); assertFalse(state.retry())
        state.loaded(); assertEquals(MapLoadPhase.FAILED, state.phase)
        val replacement = MapLoadAttempt(); replacement.loaded()
        assertEquals(MapLoadPhase.LOADED, replacement.phase)
    }
    @Test fun disposedCandidateIgnoresEveryCallback() {
        val state = MapLoadAttempt(); state.dispose()
        state.loaded(); state.timeout(); state.failed(); state.allowRetry()
        assertEquals(MapLoadPhase.LOADING, state.phase); assertFalse(state.canRetry)
    }
    @Test fun candidateReplacementHasIndependentState() {
        val old = MapLoadAttempt(); old.timeout(); old.dispose()
        val new = MapLoadAttempt(); old.loaded()
        assertEquals(MapLoadPhase.LOADING, new.phase)
    }
}

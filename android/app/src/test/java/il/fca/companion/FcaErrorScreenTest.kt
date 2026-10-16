package il.fca.companion

import il.fca.companion.ui.blockingInitialLoadError
import org.junit.Assert.*
import org.junit.Test

class FcaErrorScreenTest {
    @Test fun onlyFailedInitialLoadIsBlocking() {
        for (loading in listOf(false, true)) for (failed in listOf(false, true))
            for (usable in listOf(false, true)) {
                assertEquals(!loading && failed && !usable,
                    blockingInitialLoadError(loading, failed, usable))
            }
    }
    @Test fun retryLoadingAndRefreshErrorsDoNotReplaceUsableContent() {
        assertTrue(blockingInitialLoadError(false, true, false))
        assertFalse(blockingInitialLoadError(true, false, false))
        assertFalse(blockingInitialLoadError(false, false, true))
        assertFalse(blockingInitialLoadError(false, true, true))
    }
}

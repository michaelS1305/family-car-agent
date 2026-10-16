package il.fca.companion

import il.fca.companion.ui.EntryScreen
import il.fca.companion.ui.bootstrapLoading
import org.junit.Assert.*
import org.junit.Test

class FcaLoadingScreenTest {
    @Test fun onlyBlockingBootstrapShowsLoading() {
        for (screen in EntryScreen.entries) {
            assertEquals(screen == EntryScreen.BOOTSTRAP, bootstrapLoading(screen, true))
            assertFalse(bootstrapLoading(screen, false))
        }
    }
    @Test fun readyResumeAndBootstrapErrorNeverShowLoading() {
        repeat(3) { assertFalse(bootstrapLoading(EntryScreen.AUTHENTICATED_APP, false)) }
        assertFalse(bootstrapLoading(EntryScreen.BOOTSTRAP, false))
        assertTrue(bootstrapLoading(EntryScreen.BOOTSTRAP, true))
        assertFalse(bootstrapLoading(EntryScreen.AUTHENTICATED_APP, false))
        assertFalse(bootstrapLoading(EntryScreen.INTRO, false))
    }
}

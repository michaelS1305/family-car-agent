package il.fca.companion

import il.fca.companion.ui.*
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class AuthenticatedAppShellTest {
    @Test fun shellDefaultsToChatAndBackRevealsChat() {
        val shell = AppShellState()
        assertEquals(AppMode.CHAT, shell.mode)
        shell.select(AppMode.DASHBOARD); assertEquals(AppMode.DASHBOARD, shell.mode)
        shell.back(); assertEquals(AppMode.CHAT, shell.mode)
    }
    @Test fun rootRefreshUsesCurrentOwnerOnceAndDoesNotBlockOnFailure() = runBlocking {
        val root = AuthenticatedRootRefresh()
        val owners = mutableListOf<String>()
        root.enter("old", { it == "current" }) { error("Must not refresh stale owner") }
        root.enter("current", { true }) { owners.add(it); error("Noncritical failure") }
        root.enter("current", { true }) { error("Duplicate refresh") }
        assertEquals(listOf("current"), owners)
        root.reset()
        root.enter("new", { it == "new" }) { owners.add(it) }
        assertEquals(listOf("current", "new"), owners)
    }
}

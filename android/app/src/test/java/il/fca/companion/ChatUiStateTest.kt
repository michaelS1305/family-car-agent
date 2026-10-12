package il.fca.companion

import il.fca.companion.ui.*
import il.fca.companion.net.ChatMessage
import org.junit.Assert.*
import org.junit.Test

class ChatUiStateTest {
    @Test fun eligibilityAndInitialHistory() {
        assertFalse(ChatState().canSend("hello"))
        assertFalse(ChatState().showSuggestions())
        val ready = ChatState(historyLoaded = true)
        assertTrue(ready.canSend(" hello "))
        assertFalse(ready.canSend(" \n "))
        assertFalse(ready.canSend("a".repeat(4001)))
        assertFalse(ready.copy(sending = true).canSend("hello"))
        assertFalse(ready.copy(pendingRequest = PendingChatRequest("A", "id", "hello")).canSend("next"))
        assertTrue(ready.showSuggestions())
        assertFalse(ready.copy(historyLoading = true).showSuggestions())
        val message = ChatDisplayMessage(ChatMessage("id", "user", "hello", "2026-10-08T00:00:00Z", "processing"), ChatDisplayMessage.Delivery.PENDING)
        assertFalse(ready.copy(messages = listOf(message)).showSuggestions())
    }
    @Test fun draftClearsOnlyOnAcceptedSend() {
        var received = ""
        assertEquals("", draftAfterChatSend(" hello ") { received = it; true })
        assertEquals("hello", received)
        assertEquals(" hello ", draftAfterChatSend(" hello ") { false })
    }
}

package il.fca.companion

import il.fca.companion.ui.ChatScrollPolicy
import org.junit.Assert.*
import org.junit.Test

class ChatScrollPolicyTest {
    @Test fun initialLoadAndNewMessagesFollow() {
        val policy = ChatScrollPolicy()
        assertFalse(policy.update(emptyList(), false))
        assertTrue(policy.update(listOf("a"), true))
        assertTrue(policy.update(listOf("a", "b"), true))
    }
    @Test fun readerPositionSurvivesIncomingAndRecompositionButOwnSendFollows() {
        val policy = ChatScrollPolicy()
        policy.update(listOf("a"), true)
        policy.userScrolled(200, 48)
        assertFalse(policy.update(listOf("a", "b"), true))
        assertFalse(policy.update(listOf("a", "b"), true))
        assertFalse(policy.update(listOf("a", "b"), false))
        policy.sent()
        assertTrue(policy.update(listOf("a", "b", "own"), true))
    }
    @Test fun reachingBottomResumesFollowingAndPrependIsNotIncoming() {
        val policy = ChatScrollPolicy()
        policy.update(listOf("b"), true)
        policy.userScrolled(100, 48)
        policy.userScrolled(10, 48)
        assertFalse(policy.update(listOf("a", "b"), true))
        assertTrue(policy.update(listOf("a", "b", "c"), true))
    }
}

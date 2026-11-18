package il.fca.companion

import android.app.Application
import il.fca.companion.net.*
import il.fca.companion.ui.*
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = Application::class)
class ChatStateTest {
    private val id = "123e4567-e89b-42d3-a456-426614174000"
    private fun reply(id: String) = ChatReply(id, ChatMessage(id, "assistant", "answer", "2026-10-08T00:00:00Z", "completed"))
    private class Gateway : ChatGateway {
        val calls = mutableListOf<Triple<String,String,String>>()
        var rows = emptyList<ChatMessage>()
        var action: suspend (String) -> ChatReply = { error("Unexpected request") }
        override suspend fun history(owner: String) = rows
        override suspend fun send(owner: String, requestId: String, message: String): ChatReply {
            calls += Triple(owner, requestId, message)
            return action(requestId)
        }
    }
    @Test fun duplicateAndRetryUseOneSnapshot() = runBlocking {
        val gate = CompletableDeferred<Unit>()
        val api = Gateway().apply { action = { gate.await(); throw ChatFailure.uncertain() } }
        var ids = 0
        val vm = ChatViewModel(api, { "A" }, { ids++; id }, testScope = this)
        assertTrue(vm.sendMessage(" hello ")); assertFalse(vm.sendMessage("again"))
        yield(); gate.complete(Unit); yield()
        assertEquals(1, ids); assertEquals("hello", vm.state.pendingRequest!!.message)
        assertEquals(1, vm.state.messages.size)
        api.action = { reply(it) }
        assertTrue(vm.retryPendingRequest()); yield()
        assertEquals(api.calls[0], api.calls[1]); assertEquals(1, ids)
        assertEquals(2, vm.state.messages.size); assertNull(vm.state.pendingRequest)
        assertFalse(vm.retryPendingRequest())
    }
    @Test fun staleOwnerCannotApplyAndNewOwnerIsIndependent() = runBlocking {
        val response = CompletableDeferred<ChatReply>()
        var owner = "A"
        val api = Gateway().apply { action = { response.await() } }
        val vm = ChatViewModel(api, { owner }, { id }, testScope = this)
        vm.sendMessage("hello"); yield()
        owner = "B"; vm.activateOwner()
        response.complete(reply(id)); yield()
        assertTrue(vm.state.messages.isEmpty()); assertFalse(vm.state.sending)
    }
    @Test fun terminalAndValidation() = runBlocking {
        val api = Gateway().apply { action = { throw ChatFailure(ChatFailure.Kind.TERMINAL, code = "AI_UNAVAILABLE") } }
        val vm = ChatViewModel(api, { "A" }, { id }, testScope = this)
        assertFalse(vm.sendMessage("  ")); assertFalse(vm.sendMessage("x".repeat(4001)))
        assertTrue(api.calls.isEmpty())
        vm.sendMessage("hello"); yield()
        assertNull(vm.state.pendingRequest); assertFalse(vm.retryPendingRequest())
        assertEquals(ChatDisplayMessage.Delivery.FAILED, vm.state.messages.single().delivery)
    }
    @Test fun mismatchedReplyIsUncertainAndKeepsSnapshot() = runBlocking {
        val api = Gateway().apply { action = { reply("123e4567-e89b-42d3-a456-426614174001") } }
        val vm = ChatViewModel(api, { "A" }, { id }, testScope = this)
        vm.sendMessage("hello"); yield()
        assertEquals(id, vm.state.pendingRequest!!.requestId)
        assertEquals(1, vm.state.messages.size); assertTrue(vm.state.error!!.retryable)
        assertFalse(vm.sendMessage("different request"))
    }
    @Test fun staleHistoryCannotReplaceNewOwnerState() = runBlocking {
        val gate = CompletableDeferred<List<ChatMessage>>()
        var owner = "A"
        val api = object : ChatGateway {
            override suspend fun history(owner: String) = gate.await()
            override suspend fun send(owner: String, requestId: String, message: String) = error("Unexpected send")
        }
        val vm = ChatViewModel(api, { owner }, testScope = this)
        vm.loadHistory(); yield(); owner = "B"; vm.activateOwner()
        gate.complete(listOf(reply(id).assistant)); yield()
        assertTrue(vm.state.messages.isEmpty()); assertFalse(vm.state.historyLoading)
    }
    @Test fun retryHonorsServerDelay() = runBlocking {
        var time = 1000L
        val api = Gateway().apply { action = { throw ChatFailure(ChatFailure.Kind.RATE_LIMITED, retryAfterSeconds = 5, retryable = true) } }
        val vm = ChatViewModel(api, { "A" }, { id }, { time }, this)
        vm.sendMessage("hello"); yield()
        assertFalse(vm.retryPendingRequest()); time = 6000
        api.action = { reply(it) }; assertTrue(vm.retryPendingRequest()); yield()
        assertEquals(2, vm.state.messages.size)
    }
    @Test fun historyReplacesInsteadOfDuplicating() = runBlocking {
        val api = Gateway().apply { rows = listOf(ChatMessage(id, "user", "hello", "2026-10-08T00:00:00Z", "completed"), reply(id).assistant) }
        val vm = ChatViewModel(api, { "A" }, testScope = this)
        vm.loadHistory(); yield(); vm.loadHistory(); yield()
        assertEquals(listOf("user", "assistant"), vm.state.messages.map { it.message.role })
        api.rows = emptyList(); vm.loadHistory(); yield(); assertTrue(vm.state.messages.isEmpty())
    }
    @Test fun entryLoadsHistoryOncePerOwner() = runBlocking {
        var owner = "A"
        var loads = 0
        val api = object : ChatGateway {
            override suspend fun history(owner: String): List<ChatMessage> { loads++; return emptyList() }
            override suspend fun send(owner: String, requestId: String, message: String) = error("Unexpected send")
        }
        val vm = ChatViewModel(api, { owner }, testScope = this)
        vm.enter(); yield(); vm.enter(); yield()
        assertEquals(1, loads); assertTrue(vm.state.historyLoaded)
        owner = "B"; vm.activateOwner(); assertFalse(vm.state.historyLoaded)
        vm.enter(); yield(); assertEquals(2, loads)
    }
    @Test fun structuredAndUnstructuredFailures() {
        val e = ChatFailure.parse(429, """{"detail":{"code":"CHAT_RATE_LIMITED","message":"wait","retry_after_seconds":5}}""", "7")
        assertEquals("wait", e.serverMessage); assertEquals(7L, e.retryAfterSeconds); assertTrue(e.retryable)
        assertEquals(ChatFailure.Kind.AUTH, ChatFailure.parse(403, """{"detail":"Forbidden"}""", null).kind)
        assertTrue(ChatFailure.parse(502, "not json", null).retryable)
        assertFalse(ChatFailure.parse(502, """{"detail":{"code":"AI_UNAVAILABLE"}}""", null).retryable)
    }
    @Test fun responseAndHistoryContract() {
        val assistant = """{"role":"assistant","content":"answer","created_at":"2026-10-08T00:00:00Z"}"""
        val body = """{"request_id":"$id","status":"completed","assistant_message":$assistant}"""
        assertEquals(id, ChatApi.parseReply(body, id).requestId)
        assertTrue(runCatching { ChatApi.parseReply(body, "other") }.isFailure)
        assertTrue(ChatApi.parseHistory("""{"messages":[]}""").isEmpty())
        val history = """{"messages":[{"request_id":"$id","request_status":"failed","role":"user","content":"hello","created_at":"2026-10-08T00:00:00Z"}]}"""
        assertEquals("failed", ChatApi.parseHistory(history).single().requestStatus)
        assertTrue(runCatching { ChatApi.parseHistory(history.replace("failed", "processing")) }.isFailure)
    }
}

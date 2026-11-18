package il.fca.companion.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import il.fca.companion.net.*
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

data class PendingChatRequest(val owner: String, val requestId: String, val message: String)
data class ChatDisplayMessage(val message: ChatMessage, val delivery: Delivery) {
    enum class Delivery { PENDING, COMPLETED, FAILED }
}
data class ChatState(
    val historyLoaded: Boolean = false,
    val messages: List<ChatDisplayMessage> = emptyList(),
    val historyLoading: Boolean = false,
    val historyError: ChatFailure? = null,
    val sending: Boolean = false,
    val pendingRequest: PendingChatRequest? = null,
    val error: ChatFailure? = null,
    val retryNotBefore: Long? = null,
)

/** Main-thread actions; memory only. Phase 2 must call activateOwner on session changes.
 * activeOwner must match BOTH SessionStore.owner() and LocalStore.activeOwner().
 */
class ChatViewModel(
    private val gateway: ChatGateway,
    private val activeOwner: () -> String?,
    private val uuid: () -> String = { UUID.randomUUID().toString() },
    private val now: () -> Long = System::currentTimeMillis,
    private val testScope: CoroutineScope? = null,
) : ViewModel() {
    var state by mutableStateOf(ChatState()); private set
    private var owner: String? = null
    private var generation = 0L
    var ownerGeneration by mutableStateOf(0L); private set
    private val scope get() = testScope ?: viewModelScope

    fun activateOwner() {
        val current = activeOwner()
        if (current != owner) {
            generation++
            ownerGeneration = generation
            owner = current
            state = ChatState()
        }
    }
    fun enter() {
        activateOwner()
        if (!state.historyLoaded && !state.historyLoading && state.historyError == null) loadHistory()
    }
    private fun valid(expected: String, version: Long): Boolean {
        activateOwner()
        return owner == expected && generation == version
    }
    fun loadHistory() {
        activateOwner()
        val current = owner ?: return
        // Never overwrite an optimistic/uncertain request with a truncated history window.
        if (state.sending || state.historyLoading || state.pendingRequest != null) return
        val version = generation
        state = state.copy(historyLoading = true, historyError = null)
        scope.launch {
            try {
                val rows = gateway.history(current)
                if (valid(current, version)) state = state.copy(messages = rows.map {
                    ChatDisplayMessage(it, if (it.requestStatus == "failed") ChatDisplayMessage.Delivery.FAILED
                    else ChatDisplayMessage.Delivery.COMPLETED)
                }, historyLoading = false, historyLoaded = true)
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                if (valid(current, version)) state = state.copy(historyLoading = false,
                    historyError = e as? ChatFailure ?: ChatFailure.uncertain())
            }
        }
    }
    fun sendMessage(text: String): Boolean {
        activateOwner()
        val current = owner ?: return false
        if (state.sending || state.historyLoading || state.pendingRequest != null) return false
        val message = text.trim()
        // Backend counts Unicode code points, not UTF-16 code units.
        if (message.codePointCount(0, message.length) !in 1..4000) {
            state = state.copy(error = ChatFailure(ChatFailure.Kind.VALIDATION, code = "INVALID_MESSAGE"))
            return false
        }
        val request = PendingChatRequest(current, uuid(), message)
        state = state.copy(messages = state.messages + ChatDisplayMessage(
            ChatMessage(request.requestId, "user", message, Instant.ofEpochMilli(now()).toString(), "processing"),
            ChatDisplayMessage.Delivery.PENDING), pendingRequest = request)
        submit(request)
        return true
    }
    fun retryPendingRequest(): Boolean {
        activateOwner()
        val request = state.pendingRequest ?: return false
        if (state.sending || state.error?.retryable != true || now() < (state.retryNotBefore ?: 0)) return false
        submit(request)
        return true
    }
    private fun mark(request: PendingChatRequest, delivery: ChatDisplayMessage.Delivery) = state.messages.map {
        if (it.message.requestId == request.requestId && it.message.role == "user") it.copy(delivery = delivery) else it
    }
    private fun submit(request: PendingChatRequest) {
        val version = generation
        state = state.copy(sending = true, error = null, retryNotBefore = null,
            messages = mark(request, ChatDisplayMessage.Delivery.PENDING))
        scope.launch {
            try {
                val reply = gateway.send(request.owner, request.requestId, request.message)
                if (!valid(request.owner, version)) return@launch
                if (reply.requestId != request.requestId || reply.assistant.requestId != request.requestId ||
                    reply.assistant.role != "assistant") throw ChatFailure.uncertain()
                val completed = mark(request, ChatDisplayMessage.Delivery.COMPLETED).map {
                    if (it.message.requestId == request.requestId) it.copy(message = it.message.copy(requestStatus = "completed")) else it
                }
                state = state.copy(messages = completed + ChatDisplayMessage(reply.assistant, ChatDisplayMessage.Delivery.COMPLETED),
                    sending = false, pendingRequest = null, error = null, retryNotBefore = null)
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                if (!valid(request.owner, version)) return@launch
                val failure = e as? ChatFailure ?: ChatFailure.uncertain()
                state = state.copy(sending = false, error = failure,
                    messages = mark(request, ChatDisplayMessage.Delivery.FAILED),
                    pendingRequest = if (failure.retryable) request else null,
                    retryNotBefore = failure.retryAfterSeconds?.let { now() + it * 1000 })
            }
        }
    }
}

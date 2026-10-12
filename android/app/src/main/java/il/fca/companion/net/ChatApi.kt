package il.fca.companion.net

import java.io.IOException
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

data class ChatMessage(val requestId: String, val role: String, val content: String,
    val timestamp: String, val requestStatus: String)
data class ChatReply(val requestId: String, val assistant: ChatMessage)
interface ChatGateway {
    suspend fun history(owner: String): List<ChatMessage>
    suspend fun send(owner: String, requestId: String, message: String): ChatReply
}

class ChatApi(private val api: FcaApi) : ChatGateway {
    private suspend fun <T> request(block: () -> T): T = withContext(Dispatchers.IO) {
        try { block() }
        catch (e: CancellationException) { throw e }
        catch (e: ChatFailure) { throw e }
        catch (e: HttpFailure) { throw ChatFailure.parse(e.status, null, null) }
        catch (_: IOException) { throw ChatFailure.uncertain() }
        catch (_: Exception) { throw ChatFailure.uncertain() }
    }
    override suspend fun history(owner: String) = request {
        parseHistory(api.chat(owner, "/api/chat/history?limit=30", "GET", null))
    }
    override suspend fun send(owner: String, requestId: String, message: String) = request {
        parseReply(api.chat(owner, "/api/chat", "POST",
            JSONObject().put("request_id", requestId).put("message", message)), requestId)
    }
    companion object {
        private fun string(obj: JSONObject, key: String) = obj.opt(key) as? String ?: error("Invalid response")
        private fun message(obj: JSONObject, id: String, status: String): ChatMessage {
            UUID.fromString(id)
            val role = string(obj, "role").also { require(it == "user" || it == "assistant") }
            val timestamp = string(obj, "created_at").also { Instant.parse(it) }
            return ChatMessage(id, role, string(obj, "content"), timestamp, status)
        }
        internal fun parseReply(body: String, expected: String): ChatReply {
            val obj = JSONObject(body)
            require(string(obj, "request_id") == expected && string(obj, "status") == "completed")
            val assistant = message(obj.getJSONObject("assistant_message"), expected, "completed")
            require(assistant.role == "assistant")
            return ChatReply(expected, assistant)
        }
        internal fun parseHistory(body: String): List<ChatMessage> {
            val items = JSONObject(body).getJSONArray("messages")
            return (0 until items.length()).map { index ->
                val obj = items.getJSONObject(index)
                val status = string(obj, "request_status").also { require(it in setOf("completed", "failed")) }
                message(obj, string(obj, "request_id"), status)
            } // Server returns chronological order; preserve its ordering for equal timestamps.
        }
    }
}

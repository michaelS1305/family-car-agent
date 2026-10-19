package il.fca.companion.push

import il.fca.companion.net.HttpFailure
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/** Single-process coordinator. HTTP never holds the state monitor, so logout can
 * fence a running request and remove displayed notifications immediately.
 * Each worker pass has finite calls; retries are capped and use durable request IDs.
 */
internal class PushEngine(
    initial: JSONObject,
    private val save: (JSONObject) -> Unit,
    private val identity: () -> String?,
    private val authOwner: () -> String?,
    private val call: (String, String, String, JSONObject?) -> JSONObject,
    private val token: () -> String,
    private val deleteToken: () -> Unit,
    private val display: (PushEvent) -> Boolean,
    private val clearNotifications: () -> Unit,
    private val clock: () -> Long = System::currentTimeMillis
) {
    private val gate = Any()
    private val drain = ReentrantLock()
    private var state = initial
    private fun persist() = save(JSONObject(state.toString()))
    private fun id() = UUID.randomUUID().toString()
    private fun snapshot() = synchronized(gate) { JSONObject(state.toString()) }
    private fun current(s: JSONObject): Boolean = state.optString("epoch") == s.optString("epoch") &&
        s.optString("owner").isNotEmpty() && identity() == s.optString("owner")
    private fun change(s: JSONObject, action: () -> Unit): Boolean = synchronized(gate) {
        if (!current(s)) return false
        action(); persist(); true
    }
    private fun appendRevocation(old: JSONObject, into: JSONArray) {
        val owner = old.optString("owner")
        val ref = old.optString("ref")
        if (owner.isEmpty() || ref.isEmpty()) return
        val pending = old.optJSONObject("pending")
        val possible = pending?.optLong("expected", 0)?.takeIf { it > 0 }?.plus(1)
        listOfNotNull(old.optLong("possibleGeneration").takeIf { it > 0 }, possible,
            old.optLong("generation").takeIf { it > 0 }).distinct().forEach {
            into.put(JSONObject().put("owner", owner).put("ref", ref).put("generation", it))
        }
    }
    /** Called BEFORE clearing/replacing auth or active-account state. Never waits for network. */
    fun invalidate() = synchronized(gate) {
        val revocations = state.optJSONArray("revocations") ?: JSONArray()
        appendRevocation(state, revocations)
        state = JSONObject().put("epoch", id()).put("revocations", revocations).put("resetToken", true)
        persist()
        clearNotifications()
    }
    fun activate(owner: String, family: Long) = synchronized(gate) {
        if (identity() != owner) return
        if (state.optString("owner") == owner && state.optLong("family") == family) return
        val revocations = state.optJSONArray("revocations") ?: JSONArray()
        appendRevocation(state, revocations)
        val reset = state.optBoolean("resetToken") || state.optString("owner").isNotEmpty()
        clearNotifications()
        state = JSONObject().put("owner", owner).put("family", family).put("epoch", id())
            .put("ref", id()).put("revocations", revocations).put("resetToken", reset)
        persist()
    }
    fun receive(data: Map<String, String>): Boolean = synchronized(gate) {
        if (identity() != state.optString("owner") || state.optString("owner").isEmpty()) return false
        if (refreshSignal(data)) {
            state.put("wake", state.optLong("wake") + 1); persist(); return true
        }
        if (!challengeSignal(data) || data["installation_ref"] != state.optString("ref")) return false
        val pending = state.optJSONObject("pending") ?: return false
        if (pending.optLong("expires") <= clock()) return false
        val expected = pending.optLong("expected")
        if (expected > 0 && data["generation"]?.toLongOrNull() != expected) return false
        val ref = pending.optString("challenge")
        if (ref.isNotEmpty() && ref != data["challenge_ref"]) return false
        // One short-lived encrypted slot; never put a nonce in WorkManager's database.
        pending.put("signal", JSONObject(data))
        persist(); true
    }
    fun reconcileRevocations() {
        val owner = authOwner() ?: return
        val list = snapshot().optJSONArray("revocations") ?: return
        val eligible = (0 until list.length()).map { list.getJSONObject(it) }
            .filter { it.getString("owner") == owner }.take(2)
        for (record in eligible) {
            if (authOwner() != owner) break
            val response = call(owner, "$PUSH_ROOT/installations/${record.getString("ref")}/revoke", "POST",
                JSONObject().put("expected_generation", record.getLong("generation")))
            if (response.optString("code") !in setOf("REVOKED", "REGISTRATION_UNAVAILABLE")) continue
            synchronized(gate) {
                val existing = state.optJSONArray("revocations") ?: JSONArray()
                state.put("revocations", JSONArray((0 until existing.length()).map { existing.getJSONObject(it) }
                    .filterNot { it.toString() == record.toString() }))
                persist()
            }
        }
    }
    /** false = one bounded retry opportunity is useful; no periodic registration loop. */
    fun run(stopped: () -> Boolean = { false }): Boolean = drain.withLock {
        val wake = snapshot().optLong("wake")
        val complete = pass(stopped)
        complete && snapshot().optLong("wake") == wake
    }
    private fun pass(stopped: () -> Boolean): Boolean {
        if (stopped()) return true
        try { reconcileRevocations() } catch (_: Exception) { /* retained for same-owner reconciliation */ }
        var s = snapshot()
        return try {
            if (stopped()) return true
            if (s.optBoolean("resetToken")) {
                deleteToken()
                synchronized(gate) {
                    if (state.optString("epoch") != s.optString("epoch")) return true
                    state.put("resetToken", false); persist()
                }
            }
            if (!s.has("owner") || identity() != s.optString("owner")) return true
            change(s) {
                val seen = state.optJSONObject("seen") ?: JSONObject()
                seen.keys().asSequence().toList().filter { seen.optLong(it) <= clock() }.forEach(seen::remove)
                state.put("seen", seen)
            }
            val rawToken = token()
            if (stopped()) return true
            val hash = MessageDigest.getInstance("SHA-256").digest(rawToken.toByteArray()).joinToString("") { "%02x".format(it) }
            if (!change(s) {
                if (state.optString("tokenHash") != hash) {
                    state.put("tokenHash", hash).remove("pending")
                    state.put("registered", false).put("nextAttempt", 0)
                }
            }) return true
            s = snapshot()
            if (!s.optBoolean("registered")) {
                if (s.optLong("nextAttempt") > clock()) return true
                val oldPending = s.optJSONObject("pending")
                if (oldPending == null || oldPending.optLong("expires") <= clock()) {
                    if (oldPending != null) {
                        change(s) { state.remove("pending"); state.put("nextAttempt", clock() + 300_000) }
                        return true
                    }
                    if (!change(s) { state.put("pending", JSONObject().put("request", id())
                            .put("expires", clock() + 120_000).put("attempts", 0)) }) return true
                    s = snapshot()
                }
                var pending = s.getJSONObject("pending")
                if (!pending.has("challenge")) {
                    if (pending.optInt("attempts") >= 3) return true
                    change(s) { state.getJSONObject("pending").put("attempts", pending.optInt("attempts") + 1) }
                    val reply = call(s.getString("owner"), "$PUSH_ROOT/registrations", "POST",
                        registrationBody(s.getString("ref"), pending.getString("request"), rawToken))
                    if (!change(s) {
                        val p = state.getJSONObject("pending")
                        if (reply.optString("code") in setOf("CHALLENGE_PENDING", "CHALLENGE_EXISTS") &&
                            reply.optString("status", "pending") == "pending") {
                            val ref = reply.getString("challenge_ref"); require(validRef(ref))
                            p.put("challenge", ref)
                            if (reply.has("expected_generation")) p.put("expected", reply.getLong("expected_generation"))
                            if (reply.has("expires_at")) p.put("expires", minOf(p.getLong("expires"),
                                java.time.Instant.parse(reply.getString("expires_at")).toEpochMilli()))
                        } else { state.remove("pending"); state.put("nextAttempt", clock() + 600_000) }
                    }) return true
                }
                s = snapshot()
                pending = s.optJSONObject("pending") ?: return true
                val signal = pending.optJSONObject("signal") ?: return false
                val expected = signal.getString("generation").toLong()
                if (signal.getString("challenge_ref") != pending.optString("challenge") ||
                    (pending.optLong("expected") > 0 && expected != pending.optLong("expected")) ||
                    pending.getLong("expires") <= clock()) return true
                if (!change(s) {
                    state.getJSONObject("pending").put("expected", expected)
                    // A lost confirm response can still have activated this generation.
                    // Retain it even after the short-lived challenge expires.
                    state.put("possibleGeneration", expected + 1)
                }) return true
                val reply = call(s.getString("owner"), "$PUSH_ROOT/installations/${s.getString("ref")}/confirm", "POST",
                    JSONObject().put("challenge_ref", signal.getString("challenge_ref")).put("nonce", signal.getString("nonce")))
                if (!change(s) {
                    if (reply.optString("code") == "ACTIVE" && reply.optLong("generation") == expected + 1) {
                        state.put("generation", reply.getLong("generation")).put("registered", true).remove("pending")
                        state.remove("possibleGeneration")
                    } else { state.remove("pending"); state.put("nextAttempt", clock() + 300_000) }
                }) return true
                s = snapshot()
            }
            if (!s.optBoolean("registered") || stopped()) return true
            var cursor: String? = null
            val cursors = mutableSetOf<String>()
            repeat(4) {
                if (stopped() || !synchronized(gate) { current(s) }) return true
                val page = call(s.getString("owner"), eventsPath(s.getString("ref"), s.getLong("generation"), cursor), "GET", null)
                val items = page.getJSONArray("items")
                require(items.length() <= 20)
                for (i in 0 until items.length()) {
                    val event = PushEvent.parse(items.getJSONObject(i), clock()) ?: continue
                    synchronized(gate) {
                        if (!current(s) || stopped()) return true
                        val seen = state.optJSONObject("seen") ?: JSONObject()
                        seen.keys().asSequence().toList().filter { seen.optLong(it) <= clock() }.forEach(seen::remove)
                        if (!seen.has(event.ref) && event.expires > clock() && display(event)) {
                            seen.put(event.ref, clock() + 600_000)
                        }
                        state.put("seen", seen); persist()
                    }
                }
                if (!page.getBoolean("has_more")) return true
                cursor = page.getString("next_cursor")
                require(validRef(cursor!!) && cursors.add(cursor!!))
            }
            true // A later independent hint/resume starts from page one, never a durable cursor.
        } catch (e: HttpFailure) {
            if (e.status in setOf(401, 403)) {
                change(s) {
                    state.put("registered", false).put("nextAttempt", clock() + 300_000).remove("pending")
                    clearNotifications()
                }
                true
            } else e.status !in setOf(408, 429, 500, 502, 503, 504)
        } catch (_: Exception) { false }
    }
}

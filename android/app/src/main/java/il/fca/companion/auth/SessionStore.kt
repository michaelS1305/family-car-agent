package il.fca.companion.auth

import android.content.Context
import android.net.Uri
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import il.fca.companion.BuildConfig
import il.fca.companion.net.Http
import java.security.KeyStore
import java.security.MessageDigest
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import org.json.JSONObject

class SessionStore(context: Context) {
    private val prefs = context.getSharedPreferences("auth", Context.MODE_PRIVATE)
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        return (store.getKey("fca-session", null) as? SecretKey) ?: KeyGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder("fca-session", KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    private fun read(name: String): JSONObject? {
        val value = prefs.getString(name, null) ?: return null
        val parts = value.split('.')
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.decode(parts[0], Base64.NO_WRAP)))
        return JSONObject(String(cipher.doFinal(Base64.decode(parts[1], Base64.NO_WRAP)), Charsets.UTF_8))
    }
    private fun write(name: String, value: JSONObject) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val encrypted = cipher.doFinal(value.toString().toByteArray(Charsets.UTF_8))
        check(prefs.edit().putString(name, Base64.encodeToString(cipher.iv, Base64.NO_WRAP) + "." +
            Base64.encodeToString(encrypted, Base64.NO_WRAP)).commit())
    }
    private fun random(): String = ByteArray(32).also { SecureRandom().nextBytes(it) }
        .let { Base64.encodeToString(it, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING) }

    fun beginLogin(): Uri = synchronized(lock) {
        val verifier = random()
        val nonce = random()
        write("pkce", JSONObject().put("verifier", verifier).put("nonce", nonce)
            .put("created", System.currentTimeMillis()))
        val challenge = Base64.encodeToString(MessageDigest.getInstance("SHA-256").digest(verifier.toByteArray()),
            Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
        Uri.parse(BuildConfig.SUPABASE_URL.trimEnd('/') + "/auth/v1/authorize").buildUpon()
            .appendQueryParameter("provider", "google")
            .appendQueryParameter("redirect_to", "il.fca.companion://auth/callback?nonce=$nonce")
            .appendQueryParameter("code_challenge", challenge)
            .appendQueryParameter("code_challenge_method", "s256").build()
    }
    fun finishLogin(uri: Uri): String = synchronized(lock) {
        require(uri.scheme == "il.fca.companion" && uri.host == "auth" && uri.path == "/callback")
        val pending = read("pkce") ?: error("Start sign-in again")
        require(uri.getQueryParameter("nonce") == pending.getString("nonce") &&
            System.currentTimeMillis() - pending.getLong("created") in 0..600000)
        val code = uri.getQueryParameter("code") ?: error("Sign-in incomplete")
        val session = token("pkce", JSONObject().put("auth_code", code).put("code_verifier", pending.getString("verifier")))
        save(session)
        check(prefs.edit().remove("pkce").commit())
        session.getJSONObject("user").getString("id")
    }
    private fun token(grant: String, body: JSONObject) = JSONObject(Http.request(BuildConfig.SUPABASE_URL,
        "/auth/v1/token?grant_type=$grant", "POST", body, apiKey=BuildConfig.SUPABASE_PUBLISHABLE_KEY))
    private fun save(session: JSONObject) {
        // Store only FCA auth credentials, never Google provider tokens/profile.
        write("session", JSONObject().put("access_token", session.getString("access_token"))
            .put("refresh_token", session.getString("refresh_token"))
            .put("owner", session.getJSONObject("user").getString("id"))
            .put("expires", System.currentTimeMillis() + session.getLong("expires_in") * 1000))
    }
    fun owner(): String? = synchronized(lock) { read("session")?.getString("owner") }
    fun access(owner: String, force: Boolean = false): String = synchronized(lock) {
        var session = read("session") ?: error("Sign-in required")
        check(session.getString("owner") == owner) { "Different account; event retained" }
        if (force || session.getLong("expires") <= System.currentTimeMillis() + 60000) {
            val refreshed = token("refresh_token", JSONObject().put("refresh_token", session.getString("refresh_token")))
            check(refreshed.getJSONObject("user").getString("id") == owner)
            save(refreshed)
            session = read("session")!!
        }
        session.getString("access_token")
    }
    fun signOut() = synchronized(lock) { check(prefs.edit().remove("session").remove("pkce").commit()) }
    companion object { private val lock = Any() }
}

package il.fca.companion.push

internal object PushPlatform {
    const val enabled = false
    fun token(): String = error("Push unavailable")
    fun deleteToken() = Unit
}

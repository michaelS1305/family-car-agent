package il.fca.companion.ui

/** Presentation-only following policy. Prepending history never means "new message". */
internal class ChatScrollPolicy {
    var following = true
        private set
    private var initialized = false
    private var keys = emptyList<String>()
    fun userScrolled(distanceFromEnd: Int, threshold: Int) {
        following = distanceFromEnd <= threshold
    }
    fun sent() { following = true }
    fun update(next: List<String>, ready: Boolean): Boolean {
        if (!ready) return false
        if (!initialized) {
            initialized = true; keys = next
            return following
        }
        val prepended = keys.isNotEmpty() && next.size > keys.size && next.takeLast(keys.size) == keys
        keys = next
        return following && !prepended
    }
}

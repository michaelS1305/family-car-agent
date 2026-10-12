package il.fca.companion.ui

import kotlinx.coroutines.CancellationException

/** Main-thread coordinator retained by the ViewModel across Activity recreation. */
internal class AuthenticatedRootRefresh {
    private var enteredOwner: String? = null
    fun reset() { enteredOwner = null }
    suspend fun enter(owner: String, current: (String) -> Boolean, refresh: suspend (String) -> Unit) {
        if (!current(owner) || enteredOwner == owner) return
        enteredOwner = owner
        try { refresh(owner) }
        catch (e: CancellationException) { throw e }
        catch (_: Exception) {
            // Non-critical refresh must not block the home UI. The shared helper owns diagnostics.
        }
    }
}

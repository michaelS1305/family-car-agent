package il.fca.companion.ui

internal fun ChatState.canSend(draft: String): Boolean {
    val text = draft.trim()
    return historyLoaded && !historyLoading && !sending && pendingRequest == null &&
        text.codePointCount(0, text.length) in 1..4000
}
internal fun ChatState.showSuggestions() = historyLoaded && !historyLoading && messages.isEmpty()
internal fun draftAfterChatSend(draft: String, send: (String) -> Boolean) =
    if (send(draft.trim())) "" else draft

import {
  sendChatMessage,
  type ChatHistoryMessage,
  type ChatResponse,
} from '../api/apiClient.ts'

type ChatSender = typeof sendChatMessage

type ChatRequest = {
  requestId: string
  message: string
}

export function pendingRequestNeedsRetry(
  request: ChatRequest,
  history: ChatHistoryMessage[],
) {
  return !history.some((message) => message.request_id === request.requestId)
}

type ChatSubmissionCallbacks = {
  onStart: (request: ChatRequest) => void
  onSuccess: (response: ChatResponse, request: ChatRequest) => void
  onError: (error: unknown, request: ChatRequest) => void
  onFinish: () => void
}

export function createChatRequestRunner(sender: ChatSender = sendChatMessage) {
  let active = false

  return {
    isActive: () => active,
    async run(
      accessToken: string,
      request: ChatRequest,
      callbacks: ChatSubmissionCallbacks,
    ) {
      if (active) return false
      active = true
      callbacks.onStart(request)
      try {
        const response = await sender(
          accessToken,
          request.requestId,
          request.message,
        )
        callbacks.onSuccess(response, request)
      } catch (error) {
        callbacks.onError(error, request)
      } finally {
        active = false
        callbacks.onFinish()
      }
      return true
    },
  }
}

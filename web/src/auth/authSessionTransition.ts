export type AppliedAccessToken = string | null | undefined

export type AuthSessionUpdate =
  | 'initial_session'
  | 'token_changed'
  | 'session_removed'
  | 'same_token'

export function classifyAuthSessionUpdate(
  appliedAccessToken: AppliedAccessToken,
  nextAccessToken: string | null,
): AuthSessionUpdate {
  if (appliedAccessToken === nextAccessToken) return 'same_token'
  if (appliedAccessToken === undefined) return 'initial_session'
  if (nextAccessToken === null) return 'session_removed'
  return 'token_changed'
}

export function wasSessionReadSuperseded(
  revisionWhenReadStarted: number,
  currentAuthEventRevision: number,
) {
  return revisionWhenReadStarted !== currentAuthEventRevision
}

# Native Chat (Dev)

`ContentView.ready` opens `AuthenticatedAppShell`. The shell owns one memory-only
`ChatModel`; Chat remains mounted when the explicitly temporary Dashboard is shown.
The custom mode bar is shared and hidden while the keyboard is visible. No new
authentication manager, persistent chat cache, dependency or asset is introduced.

`EntryModel` implements `ChatGateway` using its existing SessionManager. The context
includes Supabase owner, FCA user/family, session generation and Entry version.
Results are checked after suspension; model state is cleared when context changes.
A 401 refreshes once with the same request. This is not a membership subscription:
remote membership changes still depend on server authorization and account refresh.

`AuthAPI` uses a separate ephemeral, redirect-blocking URLSession for Chat (90-second
request/resource budgets for POST; GET request timeout 15 seconds). Authentication
and Onboarding timeout settings remain unchanged. History is limited to 30 as on
Android. There is no streaming, pagination or automatic retry/polling.

Retries preserve UUID and text; unresolved sends block history replacement and new
sends. Cancellation/timeouts do not establish that the server stopped processing.
HTTP/body retry delays are combined conservatively. Raw errors are not displayed or
logged. Duplicate history identities and mismatched reply identities fail closed.

## Local checks

Run `bash Checks/run-ci-checks.sh` with `SWIFT_BIN` pointing to the available Swift
compiler. This includes Chat logic, session integration, resource checks and existing
authentication diagnostics. `check-chat-resources.py <app-path>` checks packaged assets.
Linux logic checks use ObservableObject shims; they do not exercise SwiftUI rendering.

For a Dev build use the established xtool `dev build --configuration debug` command
without `--sign`. Do not use `dev run` for validation. No installation is implied.

## Device acceptance still required

- Compare empty/active conversation with the supplied Android screenshots on iPhone 13.
- Check RTL, Hebrew/English/emoji input, safe areas and keyboard; confirm the mode bar hides.
- Verify initial scroll, own-send scroll, incoming replies while reading older messages,
  keyboard resize and retained draft/scroll when returning from temporary Dashboard.
- Check loading, history failure, uncertain send/retry, retry cooldown and account switching.
- Verify real Dev responses and authentication refresh separately with user authorization.

The header uses an alpha gradient mask on scrolling content, not a Material surface.
This is a clean fade, NOT a variable blur; empty header pixels retain the Chat background.
The viewport extends behind the top safe area while an equal
content inset keeps the first message below the unchanged wordmark at rest.
The floating icon-only mode bar uses interactive native Liquid Glass on iOS 26+, with ultraThinMaterial
on iOS 17–18. One capsule does not require GlassEffectContainer. SF Symbol
`arrow.up.circle` replaces the Android send drawable. UI is light, per the supplied
screenshots; this task does not introduce an application-wide dark theme.

Navigation PNGs under `icons/navigation` are lossless crops of the original archive
artwork, excluding the separate Hebrew lettering band. Two transparent pixels border
the exact original RGBA pixels. `check-navigation-assets.py` verifies this without
external dependencies; `--create` writes only these derivatives and rejects unrelated artwork.
At a 34-point frame, artwork widths are about 33.4 points. The control row retains
50-point touch height and reserves 60 points below content when visible. Glass over
a uniform light background is inherently subtle; verify selection contrast on device.

Cold startup uses a branded loading view until saved-session bootstrap completes,
with a generic retry presentation on transient failure. No saved account data is
displayed before verification. `resume()` retains the existing verified shell;
its credential validation and revocation behavior are unchanged. There is no
artificial delay or additional authentication request.

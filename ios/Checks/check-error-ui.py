from pathlib import Path
root = Path(__file__).resolve().parents[1] / 'Sources/FamilyCarAgent'
content = (root / 'ContentView.swift').read_text(encoding='utf-8')
loading = content.split('private struct BootstrapLoadingView: View {', 1)[1]
assert 'AppAssetImage(path: ChatStyle.wordmark)\n                .frame(maxWidth: 255).frame(height: 85).scaleEffect(0.9).blendMode(.multiply)' in loading
assert 'חזרה לכניסה' not in loading and 'let exit:' not in loading
assert 'guard !busy, !retrying else { return }' in loading
assert '.disabled(busy || retrying)' in loading
assert 'Task { await retry(); retrying = false }' in loading
assert 'retry: { await model.retry() }' in content
shell = (root / 'AuthenticatedAppShell.swift').read_text(encoding='utf-8')
assert 'AppErrorDialog(presentation: errors)' in shell
assert 'guard navigation.isRoot, chat.mode == .chat' in shell
assert 'entry.chatIdentity == identity && chat.historyLoaded && chat.historyError == nil' in shell
assert 'await chat.waitForOperation()' in shell
assert 'failure.retryAfter == 0' in shell
assert 'errors.reset()' in shell
assert 'chat.send()' not in shell and 'chat.retry()' not in shell
chat = (root / 'Chat/ChatScreen.swift').read_text(encoding='utf-8')
assert 'Button("נסה שוב", action: retryHistory)' in chat
assert 'model.retry()' in chat and 'model.canRetry(at: context.date)' in chat
view = (root / 'Errors/AppErrorDialog.swift').read_text(encoding='utf-8-sig')
assert '.disabled(presentation.stage == .retrying)' in view
assert '.accessibilityAddTraits(.isModal)' in view
print('PASS: auth logo configuration/retry, shared history-only integration and existing write safeguards (static)')

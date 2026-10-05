import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { notificationPermissionLabel } from '../src/push/pushNotifications.ts'
import { confirmAccountDeletion, getDeletionPreview, getDeletionStatus, getCurrentUser, ApiRequestError } from '../src/api/apiClient.ts'
import { clearDeletionLocalState } from '../src/auth/deletionCleanup.ts'
import { createDeletionSubmissionGuard } from '../src/auth/deletionSubmission.ts'

const deletionSource = readFileSync(new URL('../src/components/AccountDeletionPanel.tsx', import.meta.url), 'utf8')

test('deletion requests derive target only from bearer identity and require explicit confirmation', async () => {
  const calls: Array<{ url: string; init: RequestInit }> = []
  const fetcher = (async (url: string, init: RequestInit) => {
    calls.push({ url, init })
    return new Response(JSON.stringify(init.method === 'POST' ? { status: 'draining' } : { status: 'auth_pending' }), { status: 202 })
  }) as typeof fetch
  assert.deepEqual(await confirmAccountDeletion('test-bearer', { fetcher }), { status: 'draining' })
  assert.equal(calls[0].url, '/api/account/deletion')
  assert.deepEqual(JSON.parse(String(calls[0].init.body)), { confirmation: 'DELETE_MY_ACCOUNT' })
  assert.equal((calls[0].init.headers as Record<string, string>).Authorization, 'Bearer test-bearer')
  assert.deepEqual(await getDeletionStatus('test-bearer', { fetcher }), { status: 'auth_pending' })
  assert.equal(calls[1].init.body, undefined)
})

test('deletion preview and status reject malformed responses and preserve errors', async () => {
  for (const consequence of ['personal', 'management_transferred', 'family_deleted']) {
    const fetcher = (async () => new Response(JSON.stringify({ consequence }))) as typeof fetch
    assert.deepEqual(await getDeletionPreview('token', { fetcher }), { consequence })
  }
  const malformed = (async () => new Response(JSON.stringify({ status: ['completed'] }))) as typeof fetch
  await assert.rejects(getDeletionStatus('token', { fetcher: malformed }), ApiRequestError)
  const failed = (async () => { throw new Error('network') }) as typeof fetch
  await assert.rejects(confirmAccountDeletion('token', { fetcher: failed }), ApiRequestError)
})

test('pending deletion is never misclassified as unmapped onboarding', async () => {
  const fetcher = (async () => new Response(JSON.stringify({ detail: { code: 'ACCOUNT_UNAVAILABLE' } }), { status: 403 })) as typeof fetch
  await assert.rejects(getCurrentUser('token', { fetcher, baseUrl: 'http://backend.test' }), (error: unknown) => error instanceof ApiRequestError && error.code === 'ACCOUNT_UNAVAILABLE')
})

test('deletion submission prevents parallel and already-accepted double submission', async () => {
  const submit = createDeletionSubmissionGuard()
  let finish!: (accepted: boolean) => void
  let calls = 0
  const operation = () => { calls++; return new Promise<boolean>((resolve) => { finish = resolve }) }
  const first = submit(operation)
  await submit(operation)
  assert.equal(calls, 1)
  finish(true); await first
  await submit(operation)
  assert.equal(calls, 1)
})

test('uncertain deletion submission remains retryable without claiming success', async () => {
  const submit = createDeletionSubmissionGuard()
  let calls = 0
  await submit(async () => { calls++; return false })
  await submit(async () => { calls++; return true })
  assert.equal(calls, 2)
})

test('local deletion cleanup removes only FCA drafts/preferences/pending chat, not unrelated storage', () => {
  const values = new Map([['family-car-agent:onboarding-draft', 'private'], ['family-car-agent:chat-pending:v1:id', 'private'], ['family-car-agent:carplay-setup', 'private'], ['family-car-agent:preferences', '{}'], ['other-app', 'keep']])
  const storage = { get length() { return values.size }, key: (index: number) => [...values.keys()][index] ?? null, removeItem: (key: string) => { values.delete(key) } } as Storage
  clearDeletionLocalState([storage])
  assert.deepEqual([...values], [['other-app', 'keep']])
  assert.doesNotThrow(() => clearDeletionLocalState([{ get length() { throw new Error('restricted') } } as Storage, null]))
})

test('deletion UI warns for all authoritative consequences and reports pending truthfully', () => {
  assert.match(deletionSource, /לא ניתן לבטל את המחיקה/)
  assert.match(deletionSource, /management_transferred/)
  assert.match(deletionSource, /family_deleted/)
  assert.match(deletionSource, /ניהול המשפחה יועבר/)
  assert.match(deletionSource, /גם המשפחה והמידע שלה/)
  assert.match(deletionSource, /אני מאשר\/ת מחיקה לצמיתות/)
  assert.match(deletionSource, /submitOnce\.current/)
  assert.match(deletionSource, /ההשלמה תימשך גם לאחר סגירת האפליקציה/)
  assert.match(deletionSource, /phase === 'completed' \? <p role="status">החשבון נמחק/)
  assert.match(deletionSource, /await onLogout\(\)/)
  assert.match(deletionSource, /clearLocal\(\)/)
})

const settingsSource = readFileSync(
  new URL('../src/components/SettingsScreen.tsx', import.meta.url),
  'utf8',
)
const dashboardSource = readFileSync(
  new URL('../src/components/DashboardScreen.tsx', import.meta.url),
  'utf8',
)
const appCssSource = readFileSync(new URL('../src/App.css', import.meta.url), 'utf8')
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
const legalSource = readFileSync(new URL('../src/legal/legalDocuments.ts', import.meta.url), 'utf8')

test('settings is a dedicated Dashboard category with the shared identity and icon', () => {
  assert.match(dashboardSource, /<SettingsScreen/)
  assert.match(dashboardSource, /<SettingsScreen/)
  assert.match(settingsSource, /<h1>Family Car Agent<\/h1>/)
  assert.match(settingsSource, /<DashboardCategoryIcon icon="settings"/)
  assert.match(settingsSource, /<h2>הגדרות<\/h2>/)
  assert.doesNotMatch(dashboardSource, /CategoryPlaceholderScreen/)
})

test('screen contains the approved phase-one groups and exact account order', () => {
  for (const title of ['חשבון', 'תצוגה', 'הרשאות']) {
    assert.match(settingsSource, new RegExp(`>${title}<`))
  }
  const account = ['>שם<', '>המשפחה שלי<', '>אימייל<', '>קוד חיבור ל־CarPlay<']
  let previous = -1
  for (const marker of account) {
    const index = settingsSource.indexOf(marker)
    assert.ok(index > previous)
    previous = index
  }
  assert.match(settingsSource, /מצב תצוגה/)
  assert.match(settingsSource, /גודל טקסט/)
  assert.match(settingsSource, /שליחת התראות/)
  assert.match(settingsSource, /מיקום/)
  assert.match(settingsSource, /CarPlay/)
})

test('account values use a two-column grid and email comes read-only from Supabase session', () => {
  assert.match(appCssSource, /\.settings-row,[\s\S]*?grid-template-columns:/)
  assert.doesNotMatch(appCssSource, /button\.settings-row:not\(\.settings-row-danger\)::after/)
  assert.match(settingsSource, /userEmail: string/)
  assert.match(appSource, /userEmail=\{session\.user\.email \?\? ''\}/)
  assert.doesNotMatch(settingsSource, /type="email"|onChange=.*userEmail/)
})

test('personal CarPlay code is masked by default and uses the existing authenticated setup source', () => {
  assert.match(settingsSource, /prepareCarPlaySetup\(accessToken, \{ signal: controller\.signal \}\)/)
  assert.match(settingsSource, /\[connectionCodeVisible, setConnectionCodeVisible\] = useState\(false\)/)
  assert.match(settingsSource, /connectionCodeVisible \? connectionCode : '••••••••••••'/)
  assert.match(settingsSource, /connectionCodeVisible \? 'הסתרת הקוד' : 'הצגת הקוד'/)
  assert.match(settingsSource, /setConnectionCodeVisible\(\(visible\) => !visible\)/)
})

test('personal CarPlay code can be copied exactly while it remains masked', () => {
  assert.match(settingsSource, /await copyConnectionCode\(connectionCode\)/)
  assert.match(settingsSource, /onClick=\{\(\) => void copyCode\(\)\}/)
  const copyHandler = settingsSource.slice(
    settingsSource.indexOf('const copyCode = async'),
    settingsSource.indexOf('const pushBusy'),
  )
  assert.doesNotMatch(copyHandler, /connectionCodeVisible/)
  assert.doesNotMatch(settingsSource, /localStorage|sessionStorage|shortcut_token|family_id|user_id/)
  assert.match(settingsSource, /aria-pressed=\{connectionCodeVisible\}/)
  assert.match(appCssSource, /\.settings-code-actions button[\s\S]*?min-height: 44px/)
})

test('account actions reuse Family navigation and existing bounded logout cleanup', () => {
  assert.match(settingsSource, /onClick=\{onOpenFamily\}/)
  assert.match(settingsSource, /await onLogout\(\)/)
  assert.match(dashboardSource, /onOpenFamily=\{\(\)=>openCategory\(DASHBOARD_CATEGORIES\[0\]\)\}/)
  assert.match(dashboardSource, /onLogout=\{handleLogout\}/)
})

test('permission labels represent browser state truthfully', () => {
  assert.equal(notificationPermissionLabel('granted'), 'מופעלות')
  assert.equal(notificationPermissionLabel('denied'), 'חסומות')
  assert.equal(notificationPermissionLabel('default'), 'לא הופעלו')
  assert.equal(notificationPermissionLabel('unsupported'), 'לא נתמך')
})

test('push is enabled only by switch gesture and disabled for this device', () => {
  assert.match(settingsSource, /onClick=\{togglePush\}/)
  assert.match(settingsSource, /void activatePushNotifications\(accessToken, pushConfig\)/)
  assert.match(settingsSource, /disableCurrentDevicePush\(accessToken\)/)
  assert.match(settingsSource, /pushState === 'denied'[\s\S]*?הגדרות האייפון/)
  assert.match(settingsSource, /inspectCurrentDevicePushState/)
  assert.match(settingsSource, /preloadPushConfiguration/)
})

test('navigation, focus, RTL and accessible settings controls remain consistent', () => {
  assert.match(settingsSource, /dir="rtl"/)
  assert.match(settingsSource, /backButtonRef\.current\?\.focus/)
  assert.match(settingsSource, /onClick=\{onBack\}/)
  assert.match(settingsSource, /role="switch"/)
  assert.match(settingsSource, /aria-checked=\{pushState === 'subscribed'\}/)
  assert.match(appCssSource, /\.settings-row[\s\S]*?min-height: 54px/)
  assert.match(appCssSource, /\.settings-screen button:focus-visible/)
})

test('dark mode covers the existing application surfaces without changing rotary selection mechanics', () => {
  assert.match(appCssSource, /html\[data-effective-theme='dark'\] \.main-chat-screen/)
  assert.match(appCssSource, /html\[data-effective-theme='dark'\] \.dashboard-screen/)
  assert.match(appCssSource, /\.family-member[\s\S]*?\.reservation-card[\s\S]*?\.history-current[\s\S]*?\.vehicles-development-card[\s\S]*?\.settings-card/)
  assert.match(appCssSource, /html\[data-effective-theme='dark'\] \.rotary-selection-glow/)
  assert.match(appCssSource, /html\[data-effective-theme='dark'\] \.rotary-knob::before/)
  assert.match(appCssSource, /html\[data-effective-theme='dark'\] \.rotary-knob/)
})

test('permission help, legal readers and truthful about details are present once', () => {
  assert.match(settingsSource, /shortcuts:\/\/open-shortcut\?name=Disconnect%20From%20CarPlay/)
  assert.match(settingsSource, /shortcuts:\/\//)
  assert.equal((settingsSource.match(/>פרטיות</g) ?? []).length, 1)
  assert.equal((settingsSource.match(/>תנאי שימוש</g) ?? []).length, 1)
  assert.equal((settingsSource.match(/>אודות</g) ?? []).length, 1)
  assert.match(settingsSource, /ערוץ התמיכה עדיין אינו זמין/)
  assert.match(settingsSource, /version/)
  assert.match(legalSource, /Google Maps/)
  assert.match(legalSource, /Gemini/)
  assert.doesNotMatch(legalSource, /zero retention|אפס שמירה|לא משמש.*אימון/)
})

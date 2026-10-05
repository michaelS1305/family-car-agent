import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'
import { createRequire } from 'node:module'

const familySource = readFileSync(
  new URL('../src/components/FamilyScreen.tsx', import.meta.url),
  'utf8',
)
const dashboardSource = readFileSync(
  new URL('../src/components/DashboardScreen.tsx', import.meta.url),
  'utf8',
)

// Execute the actual component handlers with deterministic hook state. No DOM
// library is required; only the loaded profile/API and clipboard are substituted.
function codeHarness(creator: boolean) {
  const states: unknown[] = [{ name: 'test', home_address: 'address', family_code: 'old123', can_edit_roles: creator, members: [] }]
  const refs: { current: unknown }[] = []
  let stateIndex = 0, refIndex = 0, calls = 0
  let resolve!: (value: { family_code: string }) => void
  let reject!: (reason: Error) => void
  const pending = new Promise<{ family_code: string }>((yes, no) => { resolve = yes; reject = no })
  const hooks = {
    useEffect: () => {},
    useRef: (value: unknown) => refs[refIndex++] ?? (refs[refIndex - 1] = { current: value }),
    useState: (initial: unknown) => {
      const index = stateIndex++
      if (!(index in states)) states[index] = initial
      return [states[index], (value: unknown) => {
        states[index] = typeof value === 'function' ? value(states[index]) : value
      }]
    },
  }
  const exports: Record<string, (props: unknown) => unknown> = {}
  const require = createRequire(import.meta.url)
  const compiled = ts.transpileModule(familySource, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  new Function('require', 'exports', compiled)((name: string) => {
    if (name === 'react') return hooks
    if (name === '../api/apiClient') return { regenerateFamilyCode: () => { calls++; return pending } }
    if (name === './DashboardCategoryIcon') return { DashboardCategoryIcon: () => null }
    return require(name)
  }, exports)
  type Element = { type?: unknown; props?: { children?: unknown; onClick?: () => void; disabled?: boolean } }
  const nodes = (value: unknown): Element[] => {
    if (Array.isArray(value)) return value.flatMap(nodes)
    if (!value || typeof value !== 'object') return []
    const element = value as Element
    return [element, ...nodes(element.props?.children)]
  }
  const render = () => {
    stateIndex = 0; refIndex = 0
    return nodes(exports.FamilyScreen({ accessToken: 'token', open: true, onBack() {} }))
  }
  const button = (label: string) => render().find(node => node.type === 'button' && node.props?.children === label)
  return { render, button, resolve, reject, calls: () => calls, code: () => (states[0] as { family_code: string }).family_code }
}

test('regenerate action is creator-only; confirmation and cancel do not send a request', () => {
  assert.equal(codeHarness(false).button('יצירת קוד חדש'), undefined)
  const harness = codeHarness(true)
  harness.button('יצירת קוד חדש')!.props!.onClick!()
  assert.ok(harness.render().some(node => node.props?.children === 'יצירת קוד חדש תבטל את הקוד הקודם להצטרפות למשפחה. בני המשפחה הקיימים לא יושפעו.'))
  harness.button('ביטול')!.props!.onClick!()
  assert.equal(harness.calls(), 0)
  assert.equal(harness.code(), 'old123')
})

test('regeneration prevents duplicate requests and success updates display and copy', async () => {
  const harness = codeHarness(true)
  harness.button('יצירת קוד חדש')!.props!.onClick!()
  const submit = harness.button('אישור יצירת קוד חדש')!.props!.onClick!
  submit(); submit()
  assert.equal(harness.calls(), 1)
  assert.equal(harness.button('יוצרים קוד…')!.props!.disabled, true)
  harness.resolve({ family_code: 'new123' })
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(harness.code(), 'new123')
  let copied = ''
  const descriptor = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (text: string) => { copied = text } } })
  try {
    harness.button('העתק')!.props!.onClick!()
    assert.equal(copied, 'new123')
  } finally {
    if (descriptor) Object.defineProperty(navigator, 'clipboard', descriptor)
    else Reflect.deleteProperty(navigator, 'clipboard')
  }
})

test('regeneration failure preserves old code and displays the existing error treatment', async () => {
  const harness = codeHarness(true)
  harness.button('יצירת קוד חדש')!.props!.onClick!()
  harness.button('אישור יצירת קוד חדש')!.props!.onClick!()
  harness.reject(new Error('failed'))
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(harness.code(), 'old123')
  assert.ok(harness.render().some(node => node.props?.children === 'לא הצלחנו ליצור קוד חדש. נסו שוב.'))
  assert.equal(harness.button('אישור יצירת קוד חדש')!.props!.disabled, false)
})

test('family category opens the real screen without a generic placeholder', () => {
  assert.match(dashboardSource, /activeCategory\.id==='family'/)
  assert.match(dashboardSource, /onClick=\{\(\)=>openCategory\(category\)\}/)
  assert.match(dashboardSource, /<FamilyScreen accessToken=\{accessToken\}/)
  assert.doesNotMatch(dashboardSource, /<CategoryPlaceholderScreen/)
})

test('family screen renders real members, address, code and separate admin status', () => {
  assert.match(familySource, /family\.members\.map/)
  assert.match(familySource, /member\.name/)
  assert.match(familySource, /מנהל המשפחה/)
  assert.match(familySource, /family\.home_address/)
  assert.match(familySource, /family\.family_code/)
  assert.doesNotMatch(familySource, /הוסף.*חבר|הוספת.*חבר/)
})

test('role presentation maps exact values and keeps null explicit', () => {
  assert.match(familySource, /parent: 'הורה'/)
  assert.match(familySource, /child: 'ילד\/ילדה'/)
  assert.match(familySource, /member\.role \? <span>\{roleLabel\(member\.role\)\}/)
  assert.match(familySource, /<option value="">ללא תפקיד<\/option>/)
})

test('roles are editable only for family creator and use public member references', () => {
  assert.match(familySource, /family\.can_edit_roles \? \(/)
  assert.match(familySource, /changeRole\(\s*member\.member_ref/)
  assert.doesNotMatch(familySource, /member\.user_id|member\.family_id|auth_user_id|shortcut_token/)
})

test('copy action copies only the family code', () => {
  assert.match(familySource, /navigator\.clipboard\.writeText\(family\.family_code\)/)
  assert.doesNotMatch(familySource, /clipboard\.writeText\(family\.home_address\)/)
})

test('back uses the existing dashboard close path so direct navigation stays mounted', () => {
  assert.match(familySource, /onClick=\{onBack\}/)
  assert.match(dashboardSource, /<div className="dashboard-content" inert=\{categoryOpen\}>/)
  assert.match(dashboardSource, /onBack=\{closeCategory\}/)
})

test('creator address editing uses resolve then explicit confirmation while members stay read-only', () => {
  assert.match(familySource, /family\.can_edit_roles \? <button[^>]*>עריכת כתובת/)
  assert.match(familySource, /resolveFamilyAddress\(accessToken, addressInput\.trim\(\)\)/)
  assert.match(familySource, /updateFamilyAddress\(accessToken, resolvedAddress\.token\)/)
  assert.match(familySource, /אישור שינוי/)
  assert.match(familySource, /הכתובת הקודמת נשארה ללא שינוי/)
  assert.match(familySource, /יש להזין את הכתובת כפי שהיא מופיעה ב-Google Maps/)
  assert.match(familySource, /maxLength=\{200\}/)
  assert.match(familySource, /error instanceof ApiRequestError/)
  assert.doesNotMatch(familySource, /family_id|user_id|car_events/)
})

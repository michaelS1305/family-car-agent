import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import App, { navigation, questions } from '../node_modules/.cache/website-tests/App.js'
const html = renderToStaticMarkup(React.createElement(App))

test('four approved navigation items target existing sections', () => {
  assert.deepEqual(navigation.map(x => x.label), ['בית', 'יכולות האפליקציה', 'מרכז תמיכה', 'יצירת קשר'])
  assert.deepEqual(navigation.map(x => x.href), ['/', '/features', '/support', '/contact'])
  for (const [, id] of html.matchAll(/href="#([^"]+)"/g)) assert.ok(html.includes(`id="${id}"`))
})
test('approved homepage sections and original hero remain in order', () => {
  const markers = ['class="site-header"', 'id="home"', 'id="capabilities"', 'id="download"', 'id="support"', 'id="faq-title"', 'class="site-footer"']
  let previous = -1
  for (const marker of markers) { const at = html.indexOf(marker); assert.ok(at > previous, marker); previous = at }
  assert.ok(html.includes('הדרך החכמה לנהל את הרכב המשפחתי'))
  assert.ok(html.includes('/assets/family-road.webp'))
  assert.equal((html.match(/<article/g) || []).length, 4)
})
test('FAQ uses accessible native disclosure with approved answers', () => {
  assert.equal((html.match(/<details>/g) || []).length, 4)
  assert.equal((html.match(/<summary>/g) || []).length, 4)
  for (const question of questions) assert.ok(html.includes(question))
  assert.doesNotMatch(html, /התשובה תתווסף בהמשך/)
  assert.ok(html.includes('הצג עוד'))
  assert.ok(html.includes('כל הקודם להזמין — זוכה ברכב!'))
})
test('unavailable services remain disabled; no invented external destinations', () => {
  assert.equal((html.match(/disabled=""/g) || []).length, 2)
  assert.doesNotMatch(html, /href="https?:/)
  assert.ok(html.includes('קישורי ההורדה יתווספו בהמשך'))
  assert.doesNotMatch(readFileSync('src/App.tsx','utf8'), /fetch\(|supabase|serviceWorker|localStorage/)
})
test('approved repository branding is copied without modifications', () => {
  const pairs = [
    ['fca-road-logo.png','../assets/branding/in-app-brand/Family Car Agent Road Logo(1).png'],
    ['fca-road-logo-white.svg','../assets/branding/in-app-brand/Family Car Agent Road Logo(1)_dark.svg'],
    ['fca-app-icon.png','../assets/branding/app-icon/family-car-agent-logo.png'],
  ]
  const hash = path => createHash('sha256').update(readFileSync(path)).digest('hex')
  for (const [copy, original] of pairs) assert.equal(hash(`public/assets/${copy}`),hash(original))
  const hero = readFileSync('public/assets/family-road.png')
  assert.equal(hero.readUInt32BE(16),1672)
  assert.equal(hero.readUInt32BE(20),941)
})
test('RTL, mobile menu, reduced motion and focus styling are retained', () => {
  assert.match(readFileSync('index.html','utf8'), /lang="he" dir="rtl"/)
  assert.match(html, /aria-controls="main-navigation"/)
  assert.match(html, /aria-expanded="false"/)
  const css = readFileSync('src/styles.css','utf8')
  assert.match(css, /max-width: 680px/)
  assert.match(css, /prefers-reduced-motion/)
  assert.match(css, /:focus-visible/)
})


test('homepage public branding, single download action and live support link', () => {
  assert.doesNotMatch(html.replace(/<[^>]*>/g,''), /\bFCA\b/)
  assert.ok(html.includes('מה אפשר לעשות עם Family Car Agent?'))
  assert.ok(html.includes('Family Car Agent תמיד איתכם'))
  assert.doesNotMatch(html, /איך זה עובד/)
  const heroActions = html.match(/class="hero-actions">([\s\S]*?)<\/div>/)[1]
  assert.equal((heroActions.match(/<a /g)||[]).length,1)
  assert.match(heroActions, /href="#download"/)
  assert.match(html, /<a class="home-support-link" href="\/support">מרכז התמיכה<\/a>/)
  assert.doesNotMatch(html, /מרכז התמיכה יתווסף בהמשך/)
  assert.match(readFileSync('src/styles.css','utf8'), /\.hero-actions\s*\{[^}]*justify-content:\s*center/)
})

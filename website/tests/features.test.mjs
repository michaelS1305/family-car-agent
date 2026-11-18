import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import App from '../node_modules/.cache/website-tests/App.js'
const render = pathname => renderToStaticMarkup(React.createElement(App,{pathname}))
const html = render('/features')
test('capabilities has the approved copy and ordered open sections',()=>{
 assert.match(html,/סוכן חכם לניהול הרכבים<br\/> של המשפחה/)
 for(const copy of ['כל מה שהמשפחה צריכה כדי לנהל יחד את הרכבים, השימוש, התחזוקה והמידע – במקום אחד.','ניהול בני המשפחה והרכבים, חלוקת השימוש ותיאום פשוט ונוח בין כולם.','חיבור וזיהוי אוטומטי, מידע חי על מי משתמש ברכב, מתי יצא ומתי חזר – עם היסטוריית שימושים מלאה.','קביעת טיפולים, מעקב אחר מועדים והיסטוריה מסודרת לכל רכב.']) assert.ok(html.includes(copy))
 let previous=-1
 for(const id of ['features-heading','cap-family','cap-live','cap-maintenance','features-download-title']) {const at=html.indexOf(`id="${id}"`);assert.ok(at>previous);previous=at}
 assert.equal((html.match(/<h1 /g)||[]).length,1)
 assert.equal((html.match(/class="capability-row /g)||[]).length,3)
})
test('both routes reuse one header/footer and expose the correct active page',()=>{
 for(const [path,label] of [['/','בית'],['/features','יכולות האפליקציה'],['/features/','יכולות האפליקציה']]) {
 const page=render(path)
 assert.equal((page.match(/<header/g)||[]).length,1)
 assert.equal((page.match(/<footer/g)||[]).length,1)
 assert.equal((page.match(/aria-current="page"/g)||[]).length,1)
 assert.ok(page.includes(`aria-current="page">${label}</a>`))
 assert.ok(page.includes('href="/features"'))
 assert.ok(page.includes('href="/"'))
 assert.ok(page.includes('href="/support"'))
 assert.ok(page.includes('href="/contact"'))
 }
})
test('all image assets exist; stores remain unavailable and legal links are active',()=>{
 for(const [,src] of html.matchAll(/(?:src|href)="(\/assets\/[^\"]+)"/g)) assert.ok(existsSync(`public${src}`),src)
 assert.ok(html.includes('/assets/family-road.webp'))
 assert.ok(html.includes('/assets/fca-road-logo.webp'))
 assert.ok(html.includes('/assets/fca-road-logo-white.svg'))
 assert.equal((html.match(/disabled=""/g)||[]).length,2)
 assert.doesNotMatch(html,/href="https?:/)
 assert.ok(html.includes('aria-hidden="true"'))
})

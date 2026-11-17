import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import App, { createFamilyGuide } from '../node_modules/.cache/website-tests/App.js'
const render = pathname => renderToStaticMarkup(React.createElement(App, { pathname }))
test('family listing exposes only the implemented guide and shared navigation', () => {
 const html = render('/support/family')
 assert.match(html, /href="\/support\/family\/create"/)
 assert.equal((html.match(/class="guide-list-card"/g)||[]).length, 3)
 for(const path of ['/support/family','/support/family/create','/support/family/create/']) {
  const page=render(path)
  assert.match(page,/aria-current="page">מרכז תמיכה/)
  assert.match(page,/<header/); assert.match(page,/<footer/)
  assert.match(page,/href="\/support"/)
 }
})
test('guide has exact approved step order, platform note, five screenshots and text-only finish', () => {
 const html=render('/support/family/create')
 assert.equal(createFamilyGuide.title,'איך יוצרים משפחה ב־Family Car Agent?')
 assert.deepEqual(createFamilyGuide.steps.map(s=>s.title),['התחלת יצירת המשפחה','התחברות לחשבון','בחירת שם למשפחה','הגדרת כתובת הבית','השלמת הפרטים','סיום ההרשמה'])
 assert.deepEqual(createFamilyGuide.steps.map(s=>s.paragraphs),[
 ['במסך הפתיחה של האפליקציה, לחצו על ״יצירת משפחה״.'],
 ['בחרו את אפשרות ההתחברות המתאימה למכשיר:'],
 ['הזינו את שם המשפחה הרצוי ולחצו על ״המשך״.'],
 ['הזינו את כתובת המגורים, כולל עיר, רחוב ומספר בית.','לאחר מכן בדקו את הכתובת שהמערכת מציגה ואשרו אותה. אם היא אינה תואמת, תוכלו לשנות אותה.'],
 ['הזינו את שמכם הפרטי, קראו ואשרו את הסעיף המשפטי ולחצו על ״יצירת המשפחה״.'],
 ['לאחר יצירת המשפחה יופיע מסך הצלחה עם קוד המשפחה.','לחצו על ״הלאה״ כדי להמשיך לאפליקציה.']])
 assert.deepEqual(createFamilyGuide.steps[1].platformNotes,['iPhone: התחברות באמצעות Google או Apple.','Android: התחברות באמצעות Google בלבד.'])
 let previous=-1
 for(const step of createFamilyGuide.steps) {
  const index=html.indexOf(`<h2>${step.title}</h2>`); assert.ok(index>previous); previous=index
  for(const p of step.paragraphs) assert.ok(html.includes(p))
 }
 assert.equal(createFamilyGuide.steps.filter(s=>s.screenshot).length,5)
 assert.equal(createFamilyGuide.steps[5].screenshot,undefined)
 assert.match(html,/<ol class="guide-steps">/)
 assert.doesNotMatch(html.split('guide-step-text-only')[1],/<figure/)
 for(const step of createFamilyGuide.steps.slice(0,5)) {
  assert.ok(step.screenshot.alt.length>10)
  assert.ok(html.includes(`alt="${step.screenshot.alt}"`))
 }
 assert.equal((html.match(/loading="lazy"/g)||[]).length,5)
 assert.equal((html.match(/rel="noopener noreferrer"/g)||[]).length,5)
})
test('five supplied original JPEGs remain byte-for-byte intact',()=>{
 const hashes=['a584344bdde3f54a9337d8f5d29772c608b9ab7e0b0aa2a1bd5c17ed9f494284','016e0a9e2076ff4515d95e594e54c1e83a737effec2bbbbe70de27e740729ac5','649bf3a0d25d33a971a0baac742466ab47927e87c4676335846edf1d29be95d2','91076a531fbc843ec18b8036e6d91c80291a23a44f7421c2cee687cdb67e0ba9','4a3525d88e5af4ce2e2099b6fd8106ff78af5af8cd9b4e014c091dacfef3cf39']
 hashes.forEach((hash,i)=>assert.equal(createHash('sha256').update(readFileSync(`public/assets/guides/create-family/step-${i+1}.jpg`)).digest('hex'),hash))
})

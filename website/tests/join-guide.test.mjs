import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import App, {joinFamilyGuide as guide} from '../node_modules/.cache/website-tests/App.js'
const render=pathname=>renderToStaticMarkup(React.createElement(App,{pathname}))
test('join guide exact approved instructions and sequence',()=>{
 assert.equal(guide.title,'איך מצטרפים למשפחה קיימת?')
 assert.deepEqual(guide.steps.map(s=>s.title),['בחירת הצטרפות למשפחה','התחברות לחשבון','הזנת שם המשפחה','אימות כתובת המשפחה','הזנת קוד המשפחה','השלמת ההצטרפות'])
 assert.deepEqual(guide.steps.map(s=>s.paragraphs),[
 ['במסך הפתיחה של Family Car Agent, לחצו על ״הצטרפות למשפחה״.'],
 ['התחברו באמצעות האפשרות המתאימה למכשיר שלכם:'],
 ['הזינו את שם המשפחה שאליה אתם רוצים להצטרף, בדיוק כפי שהוא מוגדר באפליקציה.'],
 ['הזינו את כתובת המגורים של המשפחה, כולל עיר, רחוב ומספר בית.','בדקו את הכתובת שהמערכת מצאה ואשרו אותה. אם היא אינה נכונה, בחרו באפשרות לשנות אותה.'],
 ['הזינו את קוד המשפחה שקיבלתם.','תוכלו למצוא אותו אצל מנהל המשפחה, במסך ״משפחה״ שבדשבורד, או בהודעת ההצטרפות שנשלחה אליכם.'],
 ['הזינו את שמכם הפרטי, קראו ואשרו את הסעיף המשפטי ולחצו על ״הצטרפות למשפחה״.','לאחר מכן יופיע מסך אישור ההצטרפות. לחצו על כפתור ההמשך — וזהו, אתם חלק מהמשפחה!']])
 assert.deepEqual(guide.steps[1].platformNotes,['iPhone: ניתן להתחבר באמצעות Google או Apple.','Android: ההתחברות מתבצעת באמצעות Google.'])
 const html=render('/support/family/join'); let previous=-1
 for(const step of guide.steps){const i=html.indexOf(`<h2>${step.title}</h2>`);assert.ok(i>previous);previous=i;for(const p of step.paragraphs)assert.ok(html.includes(p))}
 assert.equal((html.match(/<figure>/g)||[]).length,6)
 assert.match(html,/aria-current="page">הצטרפות למשפחה קיימת/)
 assert.match(html,/href="\/support\/family"/)
 assert.equal(render('/support/family/join/'),html)
 assert.match(render('/support/family'),/href="\/support\/family\/join"/)
 assert.match(render('/support/family'),/href="\/support\/family\/create"/)
})
test('join original screenshot bytes, paths, dimensions and accessible enlargement',()=>{
 const hashes=['a584344bdde3f54a9337d8f5d29772c608b9ab7e0b0aa2a1bd5c17ed9f494284','016e0a9e2076ff4515d95e594e54c1e83a737effec2bbbbe70de27e740729ac5','01f8811fbebdde5691bf509d52de9796b367e1caf79f0b4af21c7f02a4390a4a','30e3e91c4494d497738a2aa4f1c790efad721b5aa56d7a7685ae57aadf29b0c0','a3a971b6d5f1afdd4c667fb45fabf35734546015b6352b5083b57e8918cb839a','feb9cc25322106d83103a38db66887e31cd120f5cd8db6988c3b9e8113bd25c4']
 const html=render('/support/family/join')
 guide.steps.forEach((s,i)=>{assert.equal(s.screenshot.src,`/assets/guides/join-family/step-${i+1}.jpg`);assert.equal(createHash('sha256').update(readFileSync(`public${s.screenshot.src}`)).digest('hex'),hashes[i]);assert.equal(s.screenshot.width,i<2?591:575);assert.equal(s.screenshot.height,1280);assert.ok(html.includes(`alt="${s.screenshot.alt}"`))})
 assert.equal((html.match(/loading="lazy"/g)||[]).length,6)
 assert.equal((html.match(/rel="noopener noreferrer"/g)||[]).length,6)
})

import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {createHash} from 'node:crypto'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import App,{manageFamilyGuide as guide} from '../node_modules/.cache/website-tests/App.js'
const render=path=>renderToStaticMarkup(React.createElement(App,{pathname:path}))
test('management guide approved actions, permissions and roles',()=>{
 assert.equal(guide.title,'איך מנהלים את מסך המשפחה?')
 assert.deepEqual(guide.steps.map(s=>s.title),['הוספת בן משפחה','שינוי כתובת המשפחה','העתקת קוד המשפחה','יצירת קוד משפחה חדש','שינוי תפקידי בני המשפחה'])
 assert.deepEqual(guide.steps.map(s=>s.permission),['זמין לכל בני המשפחה.','זמין למנהל המשפחה בלבד.','זמין לכל בני המשפחה.','זמין למנהל המשפחה בלבד.','זמין למנהל המשפחה בלבד.'])
 assert.deepEqual(guide.steps.flatMap(s=>s.choices||[]),['הורה','ילד'])
 assert.deepEqual(guide.steps.map(s=>s.paragraphs),[
 ['במסך ״משפחה״, לחצו על סמל + באזור ״אנשי המשפחה״ כדי לשלוח הזמנת הצטרפות לבן משפחה נוסף.'],
 ['לחצו על סמל העיפרון באזור הכתובת.','הזינו את הכתובת החדשה, בדקו את המיקום שהמערכת מציגה במפה ובחרו אם לאשר את הכתובת או לשנות אותה.'],
 ['באזור ״קוד משפחתי״, לחצו על סמל ההעתקה כדי להעתיק את הקוד ולשתף אותו עם בני משפחה שרוצים להצטרף.'],
 ['מתחת לקוד המשפחתי מופיעה האפשרות ״יצירת קוד חדש״.','לחיצה עליה מאפשרת להחליף את קוד ההצטרפות הקיים בקוד חדש.'],
 ['מנהל המשפחה יכול להגדיר את התפקיד של כל אחד מבני המשפחה.','במסך ״משפחה״, לחצו על התפריט ״ללא תפקיד״ שלצד בן המשפחה הרצוי.','תיפתח רשימת תפקידים שממנה ניתן לבחור:']])
 const html=render('/support/family/manage');let last=-1
 for(const step of guide.steps){const i=html.indexOf(`<h2>${step.title}</h2>`);assert.ok(i>last);last=i;for(const p of step.paragraphs)assert.ok(html.includes(p));assert.ok(html.includes(`הרשאה: ${step.permission}`))}
 assert.equal((html.match(/<figure>/g)||[]).length,1)
 assert.ok(html.indexOf('<figure>')<html.indexOf('<ol class="guide-steps">'))
 assert.match(html,/aria-current="page">ניהול מסך המשפחה/)
 assert.match(html,/href="\/support\/family"/)
 assert.equal(render('/support/family/manage/'),html)
 const listing=render('/support/family');for(const slug of ['create','join','manage'])assert.ok(listing.includes(`href="/support/family/${slug}"`))
 assert.equal((listing.match(/class="guide-list-card"/g)||[]).length,3)
 assert.match(html,/alt="מסך המשפחה:/)
 assert.match(html,/rel="noopener noreferrer"/)
})
test('management screenshot asset remains original',()=>{
 const data=readFileSync(`public${guide.screenshot.src}`)
 assert.ok(data.length>1000)
 assert.equal(guide.steps.filter(s=>s.screenshot).length,0)
 assert.equal(guide.screenshot.width,591);assert.equal(guide.screenshot.height,1280)
 assert.equal(createHash('sha256').update(data).digest('hex'),'69dc0970490afefedc451adbb44aaecc087994501700c80dc14243522c9fd121')
})

import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import App,{settingsGuides as guides} from '../node_modules/.cache/website-tests/App.js'
const render=pathname=>renderToStaticMarkup(React.createElement(App,{pathname}))
test('settings listing, routes, breadcrumbs and single original screenshots',()=>{
 assert.deepEqual(guides.map(g=>g.path),['/support/settings/iphone','/support/settings/android','/support/settings/delete-account'])
 assert.deepEqual(guides.map(g=>g.title),['הגדרות, התראות ומצב תצוגה — iPhone','הגדרות, התראות ומצב תצוגה — Android','מחיקת חשבון ועזיבת משפחה'])
 assert.equal((render('/support/settings').match(/class="guide-list-card"/g)||[]).length,3)
 assert.match(render('/support'),/href="\/support\/settings">הגדרות והתראות/)
 for(const guide of guides){const html=render(guide.path);assert.equal(render(guide.path+'/'),html);assert.ok(html.includes(guide.title));assert.match(html,/href="\/support\/settings"/);assert.match(html,/aria-current="page">מרכז תמיכה/);assert.equal((html.match(/<figure>/g)||[]).length,1);assert.ok(html.includes(`src="${guide.screenshot.src}"`));assert.ok(guide.screenshot.alt.length>10);assert.ok(readFileSync('public'+guide.screenshot.src).length>1000);let last=-1;for(const step of guide.steps){const i=html.indexOf(`<h2>${step.title}</h2>`);assert.ok(i>last);last=i;for(const p of step.paragraphs)assert.ok(html.includes(p))}}
})
test('platform instructions preserve the approved distinctions',()=>{
 const [ios,android,deletion]=guides
 assert.deepEqual(guides.map(g=>g.steps.length),[4,4,3])
 for(const g of [ios,android])assert.deepEqual(g.steps.slice(0,3).map(s=>s.title),['שינוי מצב התצוגה','הרשאת מיקום','הרשאות התראות'])
 assert.deepEqual(ios.steps[0].choices,['מערכת — האפליקציה מתאימה את התצוגה למצב שמוגדר באייפון.','בהיר — האפליקציה תוצג תמיד במצב בהיר.','כהה — האפליקציה תוצג תמיד במצב כהה.'])
 assert.deepEqual(android.steps[0].choices,['מערכת — האפליקציה מתאימה את התצוגה להגדרות המכשיר.','בהיר — האפליקציה תוצג תמיד במצב בהיר.','כהה — האפליקציה תוצג תמיד במצב כהה.'])
 assert.ok(ios.steps[1].paragraphs.includes('כדי לאפשר את פעולת הזיהוי האוטומטי, הגדירו את הרשאת המיקום ל־״תמיד״.'))
 assert.ok(ios.steps[3].paragraphs.includes('שם תוכלו לבחור רכב ולנהל את הגדרות החיבור והקיצורים שלו.'))
 assert.deepEqual(android.steps[1].choices,['מותר כל הזמן.','מיקום מדויק מופעל.'])
 assert.ok(android.steps[3].paragraphs.includes('במסך ההגדרות של Android, לחצו על ״Android Companion״.'))
 assert.doesNotMatch(JSON.stringify(android),/Shortcuts|קיצורים|iPhone|אייפון/)
 assert.deepEqual(deletion.steps[2].paragraphs,['Android:','לאחר האישור תוצג חלונית שבה ניתן לבדוק את מצב מחיקת החשבון.','iPhone:','לאחר האישור ייפתח מסך ייעודי לבדיקת מצב המחיקה.','המתינו מספר שניות, לחצו על כפתור בדיקת המצב וודאו שהמחיקה אושרה והושלמה.'])
 assert.deepEqual(deletion.notes,['מחיקת החשבון היא גם הדרך לעזוב את המשפחה. הפעולה מוחקת את החשבון עצמו, ולא רק את השיוך המשפחתי.','אם מנהל המשפחה מוחק את חשבונו, האחריות לניהול עוברת לבן משפחה אחר.'])
})

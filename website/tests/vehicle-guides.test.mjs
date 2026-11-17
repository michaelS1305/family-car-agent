import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import App,{vehicleGuides as guides} from '../node_modules/.cache/website-tests/App.js'
const render=pathname=>renderToStaticMarkup(React.createElement(App,{pathname}))
test('vehicle routes, five entries and two honest future guides',()=>{
 assert.deepEqual(guides.map(g=>g.path),['/support/vehicles/add','/support/vehicles/manage','/support/vehicles/android-connection','/support/vehicles/iphone-carplay','/support/vehicles/iphone-bluetooth'])
 assert.equal((render('/support/vehicles').match(/class="guide-list-card"/g)||[]).length,5)
 assert.match(render('/support'),/href="\/support\/vehicles">ניהול רכבים/)
 assert.deepEqual(guides.map(g=>g.steps.length),[4,5,6,0,0])
 for(const g of guides){
  const html=render(g.path)
  assert.equal(render(g.path+'/'),html)
  assert.ok(html.includes(g.title))
  assert.match(html,/class="guide-back" href="\/support\/vehicles"/)
  let last=-1
  for(const step of g.steps){
   const index=html.indexOf('<h2>'+step.title+'</h2>');assert.ok(index>last);last=index
   for(const p of [...step.paragraphs,...step.choices||[],...step.trailingParagraphs||[]])assert.ok(html.includes(p))
   if(step.permission)assert.ok(html.includes(step.permission))
  }
 }
 for(const g of guides.slice(3)){
  assert.equal(g.soon,true)
  assert.match(render(g.path),/מדריך הווידאו יעלה בקרוב/)
  assert.doesNotMatch(render(g.path),/<video|<figure>|class="guide-step"/)
 }
})
test('original screenshot mapping, permissions and additional vehicle flow',()=>{
 const [add,manage]=guides
 assert.deepEqual(add.steps.map(s=>s.screenshot.src.split('/').at(-1)),['invitation.jpg','empty.jpg','add.jpg','list.jpg'])
 assert.deepEqual(manage.steps.flatMap(s=>s.screenshot?[s.screenshot.src.split('/').at(-1)]:[]),['list.jpg','details.jpg'])
 assert.equal((render(manage.path).match(/src="[^"]*details.jpg"/g)||[]).length,1)
 assert.ok(add.steps[1].paragraphs.includes('אם כבר קיימים רכבים במשפחה, תוכלו להוסיף רכב נוסף באמצעות סמל +.'))
 assert.deepEqual(add.notes,['רק מנהל המשפחה רשאי להוסיף, לערוך או למחוק רכבים.','שאר בני המשפחה יכולים לצפות ברכבים ולהשתמש ביכולות הזמינות להם.'])
 assert.deepEqual(manage.steps.slice(0,3).map(s=>s.permission),Array(3).fill('כל בני המשפחה.'))
 assert.deepEqual(manage.steps[3].choices,['צפייה — כל בני המשפחה.','הוספת טיפול — מנהל המשפחה בלבד.'])
 assert.deepEqual(manage.steps[4].choices,['צפייה — כל בני המשפחה.','עריכה — מנהל המשפחה בלבד.'])
 for(const g of [add,manage])for(const s of g.steps)if(s.screenshot){
  assert.ok(s.screenshot.alt.length>15)
  assert.equal(readFileSync('public'+s.screenshot.src).readUInt16BE(0),0xffd8)
 }
})
test('Android instructions and native non-autoplay local video',()=>{
 const g=guides[2],html=render(g.path)
 assert.deepEqual(g.steps.map(s=>s.title),['כניסה למסך הרכבים','בחירת הרכב','פתיחת הגדרות החיבור','רישום הרכב','בחירת Bluetooth','הרשאות מיקום'])
 assert.deepEqual(g.steps[5].choices,['הרשאת המיקום מוגדרת ל־״מותר כל הזמן״.','האפשרות ״מיקום מדויק״ מופעלת.'])
 assert.doesNotMatch(JSON.stringify(g),/CarPlay|Shortcuts|iPhone/)
 assert.match(html,/<video controls="" playsInline="" preload="none"/)
 assert.doesNotMatch(html,/autoPlay|autoplay|iframe/)
 assert.match(html,/aria-describedby="vehicle-video-description"/)
 assert.equal(readFileSync('public/assets/guides/vehicles/android-connection.mov').length,12693344)
})

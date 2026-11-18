import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import App,{bookingGuides as guides} from '../node_modules/.cache/website-tests/App.js'
const render=pathname=>renderToStaticMarkup(React.createElement(App,{pathname}))

test('booking listing and guide navigation reuse shared accessible infrastructure',()=>{
 assert.deepEqual(guides.map(g=>g.path),['/support/bookings/chat','/support/bookings/manage'])
 assert.deepEqual(guides.map(g=>g.title),['איך מזמינים רכב דרך הסוכן החכם?','איך מנהלים את מרכז ההזמנות?'])
 const listing=render('/support/bookings')
 assert.equal((listing.match(/class="guide-list-card"/g)||[]).length,2)
 assert.match(render('/support'),/href="\/support\/bookings">הזמנת רכב/)
 for(const g of guides){
  assert.ok(listing.includes('href="'+g.path+'"'))
  assert.ok(listing.includes(g.label))
  const html=render(g.path)
  assert.equal(render(g.path+'/'),html)
  assert.match(html,/<h1>/)
  assert.match(html,/aria-current="page">מרכז תמיכה/)
  assert.match(html,/class="guide-back" href="\/support\/bookings"/)
  assert.ok(html.includes('Android ו־iPhone'))
  let previous=-1
  for(const step of g.steps){
   const index=html.indexOf('<h2>'+step.title+'</h2>')
   assert.ok(index>previous);previous=index
   for(const text of [...step.paragraphs,...step.choices||[],...step.orderedChoices||[],...step.trailingParagraphs||[]]) assert.ok(html.includes(text))
  }
 }
})

test('approved chat instructions and conflict rules are preserved in order',()=>{
 const steps=guides[0].steps
 assert.deepEqual(steps.map(s=>s.title),['פתיחת הצ’אט','מסירת פרטי ההזמנה','אישור ההזמנה'])
 assert.deepEqual(steps[0].paragraphs,['היכנסו למסך ״צ’אט״ באפליקציה וכתבו לסוכן החכם שאתם רוצים להזמין רכב.'])
 assert.deepEqual(steps[1].paragraphs,['ציינו איזה רכב תרצו להזמין, במיוחד אם למשפחה יש כמה רכבים.','ציינו גם את טווח הזמן המבוקש:'])
 assert.deepEqual(steps[1].choices,['מועד התחלה.','מועד סיום.'])
 assert.deepEqual(steps[1].trailingParagraphs,['אפשר למסור את כל הפרטים בהודעה אחת.','אם חסר מידע, הסוכן ישאל שאלות להשלמת ההזמנה.'])
 assert.deepEqual(steps[2].paragraphs,['אם הרכב פנוי בטווח הזמן שביקשתם, הסוכן יבצע את ההזמנה ויודיע לכם בצ’אט.','אם כבר קיימת הזמנה חופפת לאותו רכב, לא ניתן להזמין אותו לאותו טווח זמן.','כל הקודם להזמין — זוכה!'])
 const html=render(guides[0].path)
 assert.ok(html.indexOf('מועד סיום.')<html.indexOf('אפשר למסור'))
})

test('calendar, expansion, ordered RTL toolbar and ownership rule',()=>{
 const steps=guides[1].steps
 assert.deepEqual(steps.map(s=>s.title),['צפייה בהזמנות בלוח השנה','צפייה בפרטי ההזמנות','שימוש בסרגל הפעולות','הרשאות לעריכה ולביטול'])
 assert.deepEqual(steps[0].paragraphs,['היכנסו למסך ״מרכז ההזמנות״ דרך הדשבורד.','בחרו תאריך בלוח השנה כדי לצפות בהזמנות של אותו יום.','נקודה כחולה מתחת לתאריך מסמנת שקיימות בו הזמנות.'])
 assert.deepEqual(steps[1].paragraphs,['החליקו את החלונית התחתונה כלפי מעלה כדי להרחיב אותה ולצפות בפרטי ההזמנות.','תוכלו לראות את הרכב, המשתמש וטווח השעות של כל הזמנה.'])
 assert.deepEqual(steps[2].paragraphs,['סרגל הפעולות מאפשר לנהל את ההזמנות.','מימין לשמאל:'])
 assert.deepEqual(steps[2].orderedChoices,['סינון — פתיחת חלונית לסינון ההזמנות.','עריכה — בחירת הזמנה קיימת ועריכת פרטיה.','מחיקה — בחירת הזמנה וביטולה.','הוספה — פתיחת חלונית ליצירת הזמנה חדשה.','חזרה להיום — איפוס התאריך הנבחר לתאריך הנוכחי.'])
 assert.deepEqual(steps[3].paragraphs,['ניתן לצפות בהזמנות של בני המשפחה.'])
 assert.equal(steps[3].permission,'עם זאת, אפשר לערוך או לבטל רק הזמנות שאתם יצרתם בעצמכם.')
 const html=render(guides[1].path)
 assert.ok(html.includes('<ol>'+steps[2].orderedChoices.map(s=>'<li>'+s+'</li>').join('')+'</ol>'))
 assert.match(html,/class="guide-permission"/)
 assert.match(readFileSync('index.html','utf8'),/dir="rtl"/)
})

test('four original JPEG assets appear once with natural dimensions and enlargement',()=>{
 const shots=[guides[0].screenshot,...guides[1].steps.flatMap(s=>s.screenshot?[s.screenshot]:[])]
 assert.deepEqual(shots.map(s=>s.src.split('/').at(-1)),['chat.jpg','calendar.jpg','details.jpg','toolbar.jpg'])
 assert.deepEqual(shots.map(s=>[s.width,s.height]),[[575,1280],[575,1280],[575,1280],[921,262]])
 const html=guides.map(g=>render(g.path)).join('')
 for(const shot of shots){
  assert.equal(html.split('src="'+shot.src+'"').length-1,1)
  assert.ok(html.includes('href="'+shot.src+'" target="_blank" rel="noopener noreferrer"'))
  assert.ok(shot.alt.length>15)
  const bytes=readFileSync('public'+shot.src)
  assert.equal(bytes.readUInt16BE(0),0xffd8)
 }
 assert.match(readFileSync('src/GuidePage.css','utf8'),/height:\s*auto/)
})

import test from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import App, {faqEntries} from '../node_modules/.cache/website-tests/App.js'
const render = pathname => renderToStaticMarkup(React.createElement(App,{pathname}))
test('all 14 FAQ entries match the exact approved wording, order and emphasis',()=>{
 assert.equal(faqEntries.length,14)
 assert.equal(createHash('sha256').update(JSON.stringify(faqEntries)).digest('hex'),'4127e592cc2f53868ae86883fa8b73b98fe76733fe22c180e3832917f49b58c0')
})
test('home and support render the same four default FAQs and accessible expansion control',()=>{
 for(const path of ['/','/support']) {
 const html=render(path)
 assert.equal((html.match(/<details>/g)||[]).length,4)
 for(const item of faqEntries.slice(0,4)) assert.ok(html.includes(item.question))
 for(const item of faqEntries.slice(4)) assert.ok(!html.includes(item.question))
 assert.match(html,/aria-expanded="false" aria-controls="[^"]+"[^>]*>הצג עוד/)
 assert.match(html,/class="faq-list faq-extra" hidden=""/)
 assert.doesNotMatch(html,/התשובה תתווסף בהמשך/)
 }
})
test('support sections, tip and only implemented family category navigation are present',()=>{
 const html=render('/support')
 assert.equal((html.match(/<article /g)||[]).length,4)
 assert.equal((html.match(/<header/g)||[]).length,1)
 assert.equal((html.match(/<footer/g)||[]).length,1)
 assert.match(html,/aria-current="page">מרכז תמיכה/)
 let previous=-1
 for(const id of ['support-heading','topics-heading','support-faq-title','contact-heading']) {const i=html.indexOf(`id="${id}"`);assert.ok(i>previous);previous=i}
 assert.ok(html.includes('כדאי לוודא שחיבור והזיהוי מוגדרים כמו שצריך, לקבלת עדכונים לייב והיסטוריית שימושים.'))
 assert.match(html,/<a class="button button-primary" href="\/contact"/)
 assert.doesNotMatch(html,/href="https?:/)
 for(const article of html.matchAll(/<article .*?<\/article>/g)) {
  if(article[0].includes('topic-family')) assert.match(article[0],/href="\/support\/family">ניהול משפחה/)
  else if(article[0].includes('topic-bell')) assert.match(article[0],/href="\/support\/settings">הגדרות והתראות/)
  else if(article[0].includes('topic-calendar')) assert.match(article[0],/href="\/support\/bookings">הזמנת רכב/)
  else if(article[0].includes('topic-car')) assert.match(article[0],/href="\/support\/vehicles">ניהול רכבים/)
  else assert.doesNotMatch(article[0],/<a |<button/)
 }
})

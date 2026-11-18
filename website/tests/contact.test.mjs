import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import App,{validateContact,contactSubjects,addAttachments,removeAttachment,maxAttachmentBytes,submissionUnavailable} from '../node_modules/.cache/website-tests/App.js'
const valid={name:' ישראל ישראלי ',email:' example@example.com ',subject:'תקלה',description:'תיאור הפנייה'}
const file=(name='screen.png',type='image/png',size=100)=>({name,type,size})
test('required fields, reasonable email format, exact subjects and description boundary',()=>{
 assert.deepEqual(validateContact(valid),{})
 assert.deepEqual(contactSubjects,['תקלה','הצעה','חוות דעת'])
 for(const key of ['name','email','subject','description']) assert.ok(validateContact({...valid,[key]:'  '})[key])
 for(const email of ['a','a@','a@b','a b@example.com','a@.com','a@@example.com']) assert.ok(validateContact({...valid,email}).email)
 assert.ok(validateContact({...valid,subject:'other'}).subject)
 assert.equal(validateContact({...valid,description:'א'.repeat(1000)}).description,undefined)
 assert.ok(validateContact({...valid,description:'א'.repeat(1001)}).description)
})
test('backend-compatible image/PDF MIME allowlist',()=>{
 for(const [name,type] of [['a.png','image/png'],['a.JPG','image/jpeg'],['a.jpeg','image/jpeg'],['a.webp','image/webp'],['a.heic','image/heic'],['a.pdf','application/pdf']]) assert.equal(addAttachments([],[file(name,type)]).error,undefined)
 for(const [name,type] of [['a.heif','image/heif'],['a.heic',''],['a.heic','image/heic-sequence'],['a.exe',''],['a.mp4','video/mp4'],['a.mp3','audio/mpeg'],['a.zip','application/zip'],['a.svg','image/svg+xml'],['a.png','application/pdf'],['a.pdf.exe','application/pdf']]) assert.ok(addAttachments([],[file(name,type)]).error)
})
test('five files and decimal 5MB/10MB limits; rejected selection retains prior files; removal is local',()=>{
 const originals=[file()]
 assert.equal(addAttachments([],Array.from({length:5},()=>file())).files.length,5)
 assert.ok(addAttachments(originals,Array.from({length:5},()=>file())).error)
 assert.equal(addAttachments([],[file('a.png','image/png',maxAttachmentBytes)]).files.length,1)
 const rejected=addAttachments(originals,[file('a.png','image/png',maxAttachmentBytes+1)])
 assert.ok(rejected.error);assert.equal(rejected.files,originals)
 assert.equal(addAttachments(originals,[file(),file('bad.exe','')]).files,originals)
 assert.deepEqual(removeAttachment([1,2,3],1),[1,3])
 assert.deepEqual(originals,[file()])
 assert.equal(maxAttachmentBytes,5_000_000)
 assert.equal(addAttachments([],[file('a.png','image/png',5_000_000),file('b.png','image/png',5_000_000)]).error,undefined)
 assert.ok(addAttachments([file('a.png','image/png',5_000_000)],[file('b.png','image/png',5_000_000),file()]).error)
 assert.ok(addAttachments([],[file('a.png','image/png',0)]).error)
})
test('contact route, accessible fields, real email link and honest unconfigured state',()=>{
 const html=renderToStaticMarkup(React.createElement(App,{pathname:'/contact'}))
 assert.match(html,/aria-current="page">יצירת קשר/)
 assert.equal((html.match(/<header/g)||[]).length,1);assert.equal((html.match(/<footer/g)||[]).length,1)
 for(const id of ['full-name','email','subject','description','attachments']) assert.ok(html.includes(`htmlFor="${id}"`)||html.includes(`for="${id}"`))
 assert.match(html,/type="email"[^>]*dir="ltr"/)
 assert.match(html,/0 \/ 1,000/)
 assert.match(html,/href="mailto:support@familycaragent.com"/)
 assert.match(html,/aria-describedby="description-count"/)
 assert.match(html,/השליחה המקוונת אינה זמינה כרגע/)
 assert.doesNotMatch(html,/09:00|18:00/)
 assert.ok(submissionUnavailable.includes('בדוא״ל התמיכה'))
 const source=readFileSync('src/ContactPage.tsx','utf8')
 assert.doesNotMatch(source,/XMLHttpRequest|sendBeacon|localStorage|sessionStorage/)
 assert.match(source,/event.preventDefault\(\)/)
 assert.match(source,/setFiles\(\[\]\)/)
 assert.match(html,/<fieldset[^>]*class="contact-fields"/)
 assert.match(html,/<button[^>]*type="submit"[^>]*disabled/)
})
test('homepage and support contact CTAs link to the real local page',()=>{
 for(const path of ['/','/support','/features']) {
 const html=renderToStaticMarkup(React.createElement(App,{pathname:path}))
 assert.ok(html.includes('href="/contact"'))
 assert.doesNotMatch(html,/אפשרות יצירת הקשר תתווסף בהמשך/)
 }
})

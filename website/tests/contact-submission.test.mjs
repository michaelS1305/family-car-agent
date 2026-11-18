import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

// Compile the real helpers in memory; no browser, API or Cloudflare network calls.
function moduleURL(file, replacements={}) {
 let code=ts.transpileModule(readFileSync(file,'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2023,module:ts.ModuleKind.ESNext}}).outputText
 for(const [from,to] of Object.entries(replacements)) code=code.replaceAll(from,to)
 return 'data:text/javascript;base64,'+Buffer.from(code).toString('base64')
}
const forms=moduleURL('src/contactForm.ts')
const {sendContact,ContactSubmission,contactEndpoint,retryDeadline}=await import(moduleURL('src/contactSubmission.ts',{'./contactForm':forms}))
const {mountTurnstile}=await import(moduleURL('src/turnstileClient.ts'))
const {validateContact}=await import(forms)
const draft={name:' בדיקה ',email:'person@example.test',subject:'תקלה',description:'תיאור בעברית'}
const response=(status,code,headers={})=>new Response(JSON.stringify({code,request_id:'a'.repeat(32)}),{status,headers})
const endpoint='https://api.example.test/api/contact'

test('configured endpoint rejects unsafe/missing configuration',()=>{
 assert.equal(contactEndpoint(''),null)
 assert.equal(contactEndpoint('https://api.example.test/'),endpoint)
 assert.equal(contactEndpoint('http://localhost:8000'),'http://localhost:8000/api/contact')
 for(const url of ['http://api.example.test','https://user:pass@example.test','https://example.test?a=b','javascript:alert(1)']) assert.equal(contactEndpoint(url),null)
})
test('multipart exact fields, original attachment, no cookies or manual boundary',async()=>{
 const file=new File(['synthetic'],'a.pdf',{type:'application/pdf'})
 let calls=0
 const result=await sendContact(endpoint,draft,[file],'token',async(url,options)=>{
  calls++;assert.equal(url,endpoint);assert.equal(options.method,'POST');assert.equal(options.credentials,'omit')
  assert.equal(options.headers,undefined);assert.equal(options.redirect,'error')
  assert.deepEqual([...options.body.keys()],['name','email','subject','description','turnstile_token','attachments'])
  assert.equal(options.body.get('name'),'בדיקה');assert.equal(options.body.get('turnstile_token'),'token')
  assert.equal(await options.body.get('attachments').text(),'synthetic')
  return response(200,'accepted')
 })
 assert.equal(calls,1);assert.equal(result.kind,'accepted')
 assert.equal(result.title,'הפנייה נשלחה בהצלחה!')
 assert.equal(result.message,'תודה שפנית אלינו. קיבלנו את פנייתך ונחזור אליך בהקדם האפשרי לכתובת הדוא״ל שציינת.')
 assert.doesNotMatch(result.message,/מספר פנייה|אין בכך אישור/)
})
test('status mapping never treats a generic 200 or lost response as acceptance',async()=>{
 for(const [status,code,kind] of [[200,'accepted','accepted'],[200,'other','uncertain'],[422,'invalid_fields','invalid'],[413,'attachment_too_large','invalid'],[415,'unsupported_attachment','invalid'],[422,'verification_failed','verification'],[503,'verification_unavailable','unavailable'],[503,'smtp_unavailable','unavailable'],[503,'service_unavailable','unavailable'],[503,'delivery_uncertain','uncertain'],[502,'unknown','uncertain']]) {
  assert.equal((await sendContact(endpoint,draft,[],'token',async()=>response(status,code))).kind,kind)
 }
 assert.equal((await sendContact(endpoint,draft,[],'token',async()=>new Response('invalid JSON',{status:200}))).kind,'uncertain')
})
test('timeout aborts once, preserves uncertainty and never retries',async()=>{
 let calls=0
 const result=await sendContact(endpoint,draft,[],'token',async(_url,{signal})=>{
  calls++;return new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(new Error('timeout')),{once:true}))
 },5)
 assert.equal(calls,1);assert.equal(result.kind,'uncertain');assert.match(result.message,/ייתכן שהפנייה נשלחה/)
 const network=await sendContact(endpoint,draft,[],'token',async()=>{throw new TypeError('offline')})
 assert.equal(network.kind,'uncertain')
})
test('rate limit parses seconds and HTTP date; conservative fallback for CORS-hidden header',async()=>{
 assert.equal(retryDeadline('30',1000),31000)
 assert.equal(retryDeadline('Thu, 01 Jan 1970 00:01:00 GMT',1000),60000)
 assert.equal(retryDeadline(null,1000),3602000)
 const result=await sendContact(endpoint,draft,[],'token',async()=>response(429,'rate_limited',{'Retry-After':'60'}))
 assert.equal(result.kind,'limited');assert.ok(result.retryUntil>Date.now()+58000)
})
test('synchronous loading latch prevents duplicate request; clears only accepted; resets token',async()=>{
 const controller=new ContactSubmission()
 let finish,requests=0,resets=0,clears=0
 const files=[new File(['x'],'a.pdf',{type:'application/pdf'})]
 const fetcher=()=>{requests++;return new Promise(resolve=>{finish=resolve})}
 const pending=controller.submit(endpoint,draft,files,'token',()=>resets++,()=>clears++,fetcher)
 assert.equal(controller.busy,true)
 assert.equal(await controller.submit(endpoint,draft,files,'token',()=>resets++,()=>clears++,fetcher),null)
 finish(response(200,'accepted'));await pending
 assert.equal(requests,1);assert.equal(resets,1);assert.equal(clears,1);assert.equal(controller.busy,false)
 assert.equal(files.length,1);assert.equal(draft.name,' בדיקה ')
})
test('failed outcomes preserve form and files; rate cooldown prevents further writes',async()=>{
 for(const [status,code] of [[422,'invalid_fields'],[503,'service_unavailable'],[503,'delivery_uncertain'],[429,'rate_limited']]) {
  const controller=new ContactSubmission();let resets=0,clears=0,calls=0
  const files=[new File(['x'],'a.pdf',{type:'application/pdf'})]
  const before=JSON.stringify(draft)
  const fetcher=async()=>{calls++;return response(status,code,{'Retry-After':'60'})}
  await controller.submit(endpoint,draft,files,'token',()=>resets++,()=>clears++,fetcher)
  assert.equal(clears,0);assert.equal(resets,1);assert.equal(JSON.stringify(draft),before);assert.equal(files.length,1)
  if(status===429) {assert.equal(await controller.submit(endpoint,draft,files,'new',()=>{},()=>{},fetcher),null);assert.equal(calls,1)}
 }
})
test('invalid fields and missing/expired verification never make a request',async()=>{
 const controller=new ContactSubmission();const fail=async()=>{assert.fail('unexpected request')}
 assert.equal((await controller.submit(endpoint,{...draft,email:'bad'},[],'token',()=>{},()=>{},fail)).kind,'invalid')
 assert.equal((await controller.submit(endpoint,draft,[],'',()=>{},()=>{},fail)).kind,'verification')
 assert.ok(validateContact({...draft,name:'x'.repeat(101)}).name)
 assert.ok(validateContact({...draft,email:'a@example.test\r\nBcc: b@example.test'}).email)
 assert.deepEqual(validateContact({...draft,description:'😀'.repeat(1000)}),{})
})
test('mocked widget token, expiration, errors, reset and unmount callbacks',()=>{
 let options,token='',errors=0,resets=0,removed=0
 const widget=mountTurnstile({render:(_element,value)=>{options=value;return 'id'},reset:id=>{assert.equal(id,'id');resets++},remove:()=>removed++},{},'public-key',value=>token=value,()=>errors++)
 assert.equal(options.sitekey,'public-key');assert.equal(options['response-field'],false)
 options.callback('fresh');assert.equal(token,'fresh')
 options['expired-callback']();assert.equal(token,'')
 options.callback('fresh2');widget.reset();assert.equal(token,'');assert.equal(resets,1)
 options['error-callback']();assert.equal(errors,1);assert.equal(token,'')
 options.callback('fresh3');options['timeout-callback']();assert.equal(token,'')
 widget.remove();options.callback('stale');assert.equal(token,'');assert.equal(removed,1)
})
test('contact retains responsive RTL/accessibility and only confirmed acceptance clears fields',()=>{
 const source=readFileSync('src/ContactPage.tsx','utf8'),css=readFileSync('src/ContactPage.css','utf8')
 assert.match(source,/aria-busy=\{busy\}/);assert.match(source,/role="status" aria-live="polite"/)
 assert.match(source,/<fieldset[^>]*disabled=\{busy\}/)
 assert.match(source,/disabled=\{busy \|\| !configured \|\| !token \|\| retryUntil>now\}/)
 assert.match(css,/@media\(max-width:680px\)/);assert.match(css,/min-width:0/)
 assert.doesNotMatch(source,/CONTACT_SMTP|TURNSTILE_SECRET/)
 assert.match(source,/result\.kind==='accepted'\s*\? <><strong>\{result\.title\}<\/strong><br\/>\{result\.message\}<\/>\s*:/)
})

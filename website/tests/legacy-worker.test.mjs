import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import { readFileSync } from 'node:fs'
import { updateLegacyWorker } from '../src/legacyWorker.ts'
const source=readFileSync('public/sw.js','utf8')
const origin='https://example.test', scope=origin+'/', name='workbox-precache-v2-'+scope
async function run({script=origin+'/sw.js', workerScope=scope, cacheName=name, valid=true, partial=false}={}) {
 const events={}, deleted=[], registrations=[]
 const entries=new Set([cacheName,'other-cache','workbox-runtime-'+scope])
 const paths=['/index.html','/registerSW.js','/images/family-car-agent-logo.png','/icons/family-car-agent-192.png','/manifest.webmanifest']
 let skips=0
 const context={URL, self:{location:{origin,href:script},registration:{scope:workerScope,unregister:async()=>{registrations.push('unregister')}},skipWaiting:async()=>{skips++},addEventListener:(name,fn)=>events[name]=fn},
  caches:{keys:async()=>[...entries],open:async()=>({keys:async()=>paths.slice(partial?1:0).map(path=>({url:origin+path+'?__WB_REVISION__=abc'})),match:async()=>({json:async()=>valid?{name:'Family Car Agent',id:'/',start_url:'/'}:{name:'Other app'}})}),delete:async key=>{deleted.push(key);return entries.delete(key)}}}
 vm.runInNewContext(source,context)
 for(let i=0;i<2;i++) {
  let pending;events.install({waitUntil:p=>pending=p});await pending
  events.activate({waitUntil:p=>pending=p});await pending
 }
 return {events,deleted,registrations,entries,skips}
}
test('replacement deletes only exact fingerprinted cache; repeating is safe',async()=>{
 const r=await run();assert.deepEqual(r.deleted,[name]);assert.equal(r.registrations.length,2)
 assert.ok(r.entries.has('other-cache'));assert.ok(r.entries.has('workbox-runtime-'+scope))
 assert.deepEqual(Object.keys(r.events).sort(),['activate','install'])
})
test('foreign scope, script, cache, missing fingerprint and foreign manifest remain intact',async()=>{
 for(const options of [{script:origin+'/other.js'},{workerScope:origin+'/other/'},{cacheName:'workbox-precache-v2-https://other.test/'},{valid:false},{partial:true}]) {
  const r=await run(options);assert.deepEqual(r.deleted,[])
  if(options.script||options.workerScope) assert.equal(r.registrations.length,0)
 }
})
test('page helper only updates exact registration; never installs or unregisters',async()=>{
 let updates=0
 const reg=(scope,scriptURL)=>({scope,active:{scriptURL},update:async()=>{updates++}})
 const good=reg(scope,origin+'/sw.js')
 await updateLegacyWorker({getRegistrations:async()=>[good,reg(scope,origin+'/other.js'),reg(origin+'/other/',origin+'/sw.js'),{...good,waiting:{scriptURL:origin+'/other.js'}}]},origin)
 assert.equal(updates,1)
 await updateLegacyWorker({getRegistrations:async()=>[]},origin)
 await updateLegacyWorker({getRegistrations:async()=>{throw Error('unavailable')}},origin)
 assert.equal(updates,1)
})

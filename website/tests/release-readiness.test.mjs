import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import App, { pages, pageMetadata, applyPageMetadata } from '../node_modules/.cache/website-tests/App.js'
const render = pathname => renderToStaticMarkup(React.createElement(App,{pathname}))
test('all 21 valid routes render and unknown routes show accessible 404 navigation',()=>{
 assert.equal(Object.keys(pages).length,21)
 for(const path of Object.keys(pages)) {
  assert.doesNotMatch(render(path),/id="not-found-title"/)
  assert.doesNotMatch(render(path==='/'?path:path+'/'),/id="not-found-title"/)
 }
 for(const path of ['/missing','/support/missing','/404','/features/unknown']) {
  const html=render(path)
  assert.match(html,/העמוד לא נמצא/); assert.match(html,/נראה שהעמוד שחיפשת לא קיים או שהועבר\./)
  assert.match(html,/href="\/">חזרה לדף הבית/); assert.match(html,/href="\/support">למרכז התמיכה/)
  assert.match(html,/class="site-header"/); assert.match(html,/class="site-footer"/)
  assert.doesNotMatch(html,/id="home"|aria-current="page"/)
  assert.equal((html.match(/<h1 /g)||[]).length,1)
 }
})
test('unique metadata, production canonicals and conservative coming-soon/404 robots',()=>{
 const titles=new Set()
 for(const path of Object.keys(pages)) {
  const m=pageMetadata(path)
  assert.ok(m.title.includes('Family Car Agent')); assert.ok(m.description.length>20)
  assert.equal(m.canonical,'https://familycaragent.com'+path)
  assert.ok(!titles.has(m.title));titles.add(m.title)
  assert.equal(pageMetadata(path+'/').canonical,m.canonical)
 }
 assert.equal(pageMetadata('/missing').canonical,null)
 assert.equal(pageMetadata('/missing').robots,'noindex,follow')
 assert.equal(pageMetadata('/support/vehicles/iphone-carplay').robots,'noindex,follow')
})
test('metadata updates remove stale canonical and social URL when moving to 404',()=>{
 const nodes=[]
 const doc={title:'',head:{appendChild(node){nodes.push(node)}},
  querySelectorAll(){return [...nodes]},
  createElement(tag){return {tag,setAttribute(key,value){this[key]=value},remove(){nodes.splice(nodes.indexOf(this),1)}}}}
 for(const path of ['/','/support','/missing','/contact']) {
  applyPageMetadata(doc,path)
  assert.equal(doc.title,pageMetadata(path).title)
  assert.equal(nodes.filter(n=>n.name==='description').length,1)
  assert.equal(nodes.filter(n=>n.rel==='canonical').length,path==='/missing'?0:1)
  assert.equal(nodes.filter(n=>n.property==='og:url').length,path==='/missing'?0:1)
  assert.equal(nodes.find(n=>n.name==='robots').content,pageMetadata(path).robots)
 }
})
test('production HTML has route metadata before JavaScript; sitemap excludes placeholders and 404',()=>{
 const sitemap=readFileSync('dist/sitemap.xml','utf8')
 const expected=Object.keys(pages).filter(path=>pages[path].index!==false).map(path=>'https://familycaragent.com'+path)
 assert.deepEqual([...sitemap.matchAll(/<loc>(.*?)<\/loc>/g)].map(m=>m[1]),expected)
 assert.doesNotMatch(sitemap,/lastmod|404|iphone-carplay|iphone-bluetooth/)
 assert.match(readFileSync('dist/robots.txt','utf8'),/Sitemap: https:\/\/familycaragent.com\/sitemap.xml/)
 for(const path of Object.keys(pages)) {
  const html=readFileSync('dist'+(path==='/'?'':path)+'/index.html','utf8')
  assert.ok(html.includes(pageMetadata(path).title))
  assert.ok(html.includes('href="'+pageMetadata(path).canonical+'"'))
  assert.match(html,/property="og:image"/)
 }
 const missing=readFileSync('dist/404.html','utf8')
 assert.match(missing,/noindex,follow/);assert.doesNotMatch(missing,/rel="canonical"|property="og:url"/)
})
test('optimized assets and extracted illustration exist, originals remain available',()=>{
 for(const name of ['fca-road-logo','fca-app-icon','family-road']) {
  const original=readFileSync('public/assets/'+name+'.png')
  const optimized=readFileSync('public/assets/'+name+'.webp')
  assert.ok(optimized.length<original.length)
  assert.equal(optimized.toString('ascii',8,12),'WEBP')
 }
 for(const name of ['not-found-illustration.webp','not-found-cloud.webp','favicon.png']) assert.ok(existsSync('public/assets/'+name))
 assert.match(render('/missing'),/width="1536" height="285"/)
 assert.match(readFileSync('src/NotFoundPage.css','utf8'),/max-width:680px/)
})

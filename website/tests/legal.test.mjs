import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import App, { pages, pageMetadata } from '../node_modules/.cache/website-tests/App.js'
const render = pathname => renderToStaticMarkup(React.createElement(App, { pathname }))
const decode = text => text.replace(/<[^>]*>/g, '').replace(/&#x27;/g, "'").replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')

for (const [name, count, sections, digest] of [
  ['terms', 95, 22, '5bceab47f75f5aecef1d92fb628494e094fda633be8477c308a2770e303e1da3'],
  ['privacy', 90, 20, 'b6eea79092503915ab30101bfcac6c6f8e54a0e9e892cd48619077d3ff66c3eb'],
]) test(`${name}: all original v1.2 paragraphs render exactly in source order`, () => {
  const data = JSON.parse(readFileSync(`src/legal/${name}.json`, 'utf8'))
  assert.equal(data.version, '1.2')
  assert.equal(data.blocks.length, count)
  assert.equal(createHash('sha256').update(data.blocks.map(b => b.text).join('\n')).digest('hex'), digest)
  const html = render('/' + name)
  const article = html.match(/<div class="legal-document">([\s\S]*?)<\/div>/)[1]
  const paragraphs = [...article.matchAll(/<(?:h1|h2|p)\b[^>]*>([\s\S]*?)<\/(?:h1|h2|p)>/g)].map(m => decode(m[1]))
  assert.deepEqual(paragraphs, data.blocks.map(b => b.text))
  assert.equal((article.match(/<h1 /g) || []).length, 1)
  assert.equal((article.match(/<h2>/g) || []).length, sections)
  assert.deepEqual(data.blocks.filter(b => b.kind === 'heading').map(b => Number(b.text.split('.')[0])), Array.from({length: sections}, (_, i) => i + 1))
  assert.match(html, /dir="rtl" aria-labelledby="legal-title"/)
  assert.doesNotMatch(html, /המסמך טרם פורסם|id="not-found-title"/)
  assert.equal(render('/' + name + '/'), html)
  assert.equal(pageMetadata('/' + name).robots, 'index,follow')
  const built = readFileSync(`dist/${name}/index.html`, 'utf8')
  assert.ok(built.includes(pageMetadata('/' + name).title))
  assert.ok(built.includes(`content="https://familycaragent.com/${name}"`))
  assert.ok(readFileSync('dist/sitemap.xml', 'utf8').includes(`<loc>https://familycaragent.com/${name}</loc>`))
})

test('every page has active legal footer links; contact has a notice without new consent', () => {
  for (const path of [...Object.keys(pages), '/missing']) {
    const footer = render(path).match(/<footer[\s\S]*?<\/footer>/)[0]
    assert.match(footer, /href="\/terms">תנאי שימוש<\/a>/)
    assert.match(footer, /href="\/privacy">מדיניות פרטיות<\/a>/)
    assert.doesNotMatch(footer, /disabled|המסמך טרם פורסם/)
  }
  const contact = render('/contact')
  assert.match(contact, /הפרטים והקבצים המצורפים שתשלחו יעובדו לצורך טיפול בפנייתכם/)
  assert.match(contact, /class="contact-privacy"[\s\S]*?href="\/privacy"/)
  assert.doesNotMatch(contact, /type="checkbox"/)
  const guide = render('/support/settings/delete-account')
  assert.match(guide, /הגשת בקשה אינה אישור להשלמת המחיקה/)
  assert.match(guide, /href="\/contact">יצירת קשר/)
  assert.match(guide, /ויש בני משפחה נוספים/)
})

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { canonicalOrigin, pages, pageMetadata, metadataEntries } from './src/pageMetadata.ts'
const escape = (value: string) => value.replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]!))
function head(path: string) {
 const m = pageMetadata(path)
 return `<title>${escape(m.title)}</title>\n` + metadataEntries(path).map(([attr,key,value])=>`<meta data-site-seo ${attr}="${key}" content="${escape(value)}" />`).join('\n') + (m.canonical ? `\n<link data-site-seo rel="canonical" href="${escape(m.canonical)}" />` : '')
}
export default defineConfig({ plugins: [react(), {
 name: 'public-page-metadata',
 enforce: 'post',
 generateBundle(_, bundle) {
  const index = bundle['index.html']
  if (!index || index.type !== 'asset') return
  const template = String(index.source)
  index.source = template.replace('</head>', head('/')+'\n</head>')
  for (const path of Object.keys(pages).filter(path=>path!=='/')) {
   this.emitFile({type:'asset',fileName:path.slice(1)+'/index.html',source:template.replace('</head>',head(path)+'\n</head>')})
  }
  this.emitFile({type:'asset',fileName:'404.html',source:template.replace('</head>',head('/404')+'\n</head>')})
  const urls = Object.keys(pages).filter(path=>pages[path].index!==false)
  this.emitFile({type:'asset',fileName:'sitemap.xml',source:'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'+urls.map(path=>`  <url><loc>${canonicalOrigin}${path}</loc></url>`).join('\n')+'\n</urlset>\n'})
  this.emitFile({type:'asset',fileName:'robots.txt',source:`User-agent: *\nAllow: /\n\nSitemap: ${canonicalOrigin}/sitemap.xml\n`})
 }
}] })

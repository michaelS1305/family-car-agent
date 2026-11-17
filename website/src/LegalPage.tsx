import terms from './legal/terms.json'
import privacy from './legal/privacy.json'
import './LegalPage.css'

// Source paragraphs are preserved verbatim; only link markup is added.
function LegalText({ text }: { text: string }) {
  return text.split(/(https:\/\/familycaragent\.com(?:\/contact)?|support@familycaragent\.com|מדיניות הפרטיות)/g).map((part, index) => {
    const href = part === 'מדיניות הפרטיות' ? '/privacy'
      : part === 'support@familycaragent.com' ? `mailto:${part}`
      : part.startsWith('https://familycaragent.com') ? part.replace('https://familycaragent.com', '') || '/' : null
    return href ? <a key={index} href={href}>{part}</a> : part
  })
}

export function LegalPage({ document }: { document: 'terms' | 'privacy' }) {
  const content = document === 'terms' ? terms : privacy
  return <article className="legal-page section-inner" dir="rtl" aria-labelledby="legal-title">
    <nav className="legal-navigation" aria-label="מסמכים משפטיים"><a href="/terms" aria-current={document === 'terms' ? 'page' : undefined}>תנאי שימוש</a><a href="/privacy" aria-current={document === 'privacy' ? 'page' : undefined}>מדיניות פרטיות</a></nav>
    <div className="legal-document">{content.blocks.map((block, index) => block.kind === 'title'
      ? <h1 id="legal-title" key={index}>{block.text}</h1>
      : block.kind === 'heading' ? <h2 key={index}>{block.text}</h2>
      : <p key={index}><LegalText text={block.text} /></p>)}</div>
  </article>
}

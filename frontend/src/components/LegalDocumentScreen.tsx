import type { LegalDocumentKind } from '../legal/legalDocuments'
import { LEGAL_DOCUMENTS } from '../legal/legalDocuments'

export function LegalDocumentScreen({ kind, onBack }: {
  kind: LegalDocumentKind
  onBack: () => void
}) {
  const document = LEGAL_DOCUMENTS[kind]
  return (
    <main className="legal-document-screen" dir="rtl">
      <header className="legal-document-header">
        <button type="button" onClick={onBack} aria-label="חזרה">→</button>
        <h1>{document.title}</h1>
        <span aria-hidden="true" />
      </header>
      <article className="legal-document-content">
        <p className="legal-document-meta">גרסה {document.version} · עודכן לאחרונה: {document.lastUpdated}</p>
        {document.sections.map((section) => (
          <section key={section.heading}>
            <h2>{section.heading}</h2>
            {section.paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
          </section>
        ))}
      </article>
    </main>
  )
}

import { manageFamilyGuide } from './manageFamilyGuide'
import { createFamilyGuide, type GuideStep } from './guideData'
import { joinFamilyGuide } from './joinFamilyGuide'
import './GuidePage.css'

export function GuideNavigation({ listing = false, label = 'יצירת משפחה', category = 'ניהול משפחה', categoryPath = '/support/family' }: { listing?: boolean; label?: string; category?: string; categoryPath?: string }) {
  return <nav className="guide-breadcrumbs" aria-label="מיקום באתר"><a href="/support">מרכז התמיכה</a><span aria-hidden="true">/</span>{listing ? <span aria-current="page">{category}</span> : <><a href={categoryPath}>{category}</a><span aria-hidden="true">/</span><span aria-current="page">{label}</span></>}</nav>
}

export function FamilyGuidesPage() {
  return <div className="guides-page section-inner"><GuideNavigation listing /><header className="guide-heading"><p className="guide-eyebrow">מדריכים</p><h1>ניהול משפחה</h1></header><div className="guide-list"><a className="guide-list-card" href="/support/family/create"><h2>יצירת משפחה</h2><p>{createFamilyGuide.title}</p><span>למדריך המלא ←</span></a><a className="guide-list-card" href="/support/family/join"><h2>הצטרפות למשפחה קיימת</h2><p>{joinFamilyGuide.title}</p><span>למדריך המלא ←</span></a><a className="guide-list-card" href="/support/family/manage"><h2>ניהול מסך המשפחה</h2><p>{manageFamilyGuide.title}</p><span>למדריך המלא ←</span></a></div><a className="guide-back" href="/support">חזרה למרכז התמיכה</a></div>
}

export function GuidePage({ title, steps, screenshot, media, category = 'ניהול משפחה', categoryPath = '/support/family', notes, label = 'יצירת משפחה', introduction = 'צילומי המסך מציגים את אפליקציית iPhone במצב כהה.' }: { title: string; steps: GuideStep[]; media?: React.ReactNode; category?: string; categoryPath?: string; notes?: string[]; screenshot?: NonNullable<GuideStep['screenshot']>; label?: string; introduction?: string }) {
  return <div className="guides-page section-inner"><GuideNavigation label={label} category={category} categoryPath={categoryPath} /><header className="guide-heading"><p className="guide-eyebrow">{category}</p><h1>{title}</h1><p>{introduction}</p></header>{media}{screenshot && <div className="guide-main-screenshot"><GuideScreenshot screenshot={screenshot} /></div>}<ol className="guide-steps">{steps.map((step, index) => <li className={`guide-step${step.screenshot ? '' : ' guide-step-text-only'}`} key={step.title}>
    <div className="guide-step-copy"><span className="guide-step-number" aria-hidden="true">{index + 1}</span><h2>{step.title}</h2>{step.paragraphs.map(text => <p key={text}>{text}</p>)}{step.choices && <ul>{step.choices.map(choice => <li key={choice}>{choice}</li>)}</ul>}{step.orderedChoices && <ol>{step.orderedChoices.map(choice => <li key={choice}>{choice}</li>)}</ol>}{step.trailingParagraphs?.map(text => <p key={text}>{text}</p>)}{step.permission && <p className="guide-permission">הרשאה: {step.permission}</p>}{step.platformNotes && <ul className="guide-platform-notes">{step.platformNotes.map(note => <li key={note}>{note}</li>)}</ul>}</div>
    {step.screenshot && <GuideScreenshot screenshot={step.screenshot} />}
  </li>)}</ol>{notes && <aside className="guide-step guide-step-text-only" aria-label="מידע חשוב"><div><h2>מידע חשוב</h2>{notes.map(note => <p key={note}>{note}</p>)}</div></aside>}<a className="guide-back" href={categoryPath}>חזרה למדריכי {category}</a></div>
}

function GuideScreenshot({ screenshot }: { screenshot: NonNullable<GuideStep["screenshot"]> }) {
    return <figure><a href={screenshot.src} target="_blank" rel="noopener noreferrer" aria-label={`הגדלת צילום: ${screenshot.alt} (בלשונית חדשה)`}><img src={screenshot.src} alt={screenshot.alt} width={screenshot.width ?? 591} height={screenshot.height ?? 1280} loading="lazy" decoding="async" /><span className="guide-image-caption">פתיחת הצילום בגודל מלא ↗</span></a></figure>
}

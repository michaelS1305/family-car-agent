import { LegalPage } from './LegalPage'
import NotFoundPage from './NotFoundPage'
import { applyPageMetadata } from './pageMetadata'
export { pages, pageMetadata, metadataEntries, applyPageMetadata } from './pageMetadata'
import { VehicleGuidesPage, VehicleGuidePage, vehicleGuides } from './VehicleGuides'
export { vehicleGuides } from './VehicleGuides'
import { BookingGuidesPage, bookingGuides } from './BookingGuides'
export { bookingGuides } from './BookingGuides'
import { SettingsGuidesPage, settingsGuides } from './SettingsGuides'
export { settingsGuides } from './SettingsGuides'
import { manageFamilyGuide } from './manageFamilyGuide'
export { manageFamilyGuide } from './manageFamilyGuide'
import { joinFamilyGuide } from './joinFamilyGuide'
export { joinFamilyGuide } from './joinFamilyGuide'
import { GuidePage, FamilyGuidesPage } from './GuidePage'
import { createFamilyGuide } from './guideData'
export { createFamilyGuide } from './guideData'
import { useEffect, useState } from 'react'
import FeaturesPage from './FeaturesPage'
import SupportPage from './SupportPage'
import ContactPage from './ContactPage'
export * from './contactForm'
import SharedFAQ from './SharedFAQ'
import { faqEntries } from './faqData'
export { faqEntries } from './faqData'
import type { ReactNode } from 'react'

export const navigation = [
  { label: 'בית', href: '/' },
  { label: 'יכולות האפליקציה', href: '/features' },
  { label: 'מרכז תמיכה', href: '/support' },
  { label: 'יצירת קשר', href: '/contact' },
] as const

export const questions = faqEntries.slice(0,4).map(entry => entry.question)

type IconName = 'download' | 'play' | 'car' | 'calendar' | 'family' | 'bell' | 'book' | 'mail' | 'chevron'
function Icon({ name }: { name: IconName }) {
  const paths: Record<IconName, ReactNode> = {
    download: <><path d="M12 3v12m-5-5 5 5 5-5M4 15v5h16v-5" /></>,
    play: <path d="m8 4 12 8-12 8Z" />,
    car: <><path d="m4 10 2-6h12l2 6M3 18v3m18-3v3M2 11c0-1 1-2 2-2h16c1 0 2 1 2 2v7H2Z" /><path d="M6 13h1m10 0h1M7 17h10" /></>,
    calendar: <><rect x="3" y="5" width="18" height="17" rx="2" /><path d="M7 2v6m10-6v6M3 11h18" /></>,
    family: <><circle cx="12" cy="5" r="3" /><circle cx="4" cy="9" r="2" /><circle cx="20" cy="9" r="2" /><path d="M6 22v-4a6 6 0 0 1 12 0v4M1 20v-4a4 4 0 0 1 4-4m18 8v-4a4 4 0 0 0-4-4" /></>,
    bell: <><path d="M4 17c2-2 2-3 2-7a6 6 0 0 1 12 0c0 4 0 5 2 7v2H4ZM10 22h4M12 2V0" /></>,
    book: <><path d="M12 5C9 2 4 2 1 4v17c3-2 8-2 11 0 3-2 8-2 11 0V4c-3-2-8-2-11 1Zm0 0v16" /></>,
    mail: <><rect x="1" y="4" width="22" height="16" rx="1" /><path d="m2 5 10 8L22 5" /></>,
    chevron: <path d="m6 9 6 6 6-6" />,
  }
  return <svg className={`icon icon-${name}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

function Header({ activeIndex }: { activeIndex: number }) {
  const [open, setOpen] = useState(false)
  return <header className="site-header">
    <div className="header-inner">
      <a className="header-brand" href="/" aria-label="Family Car Agent — בית"><img src="/assets/fca-road-logo.webp" alt="Family Car Agent" width="2048" height="682" /></a>
      <button className="menu-toggle" aria-label={open ? 'סגירת התפריט' : 'פתיחת התפריט'} aria-expanded={open} aria-controls="main-navigation" onClick={() => setOpen(!open)}><span /><span /><span /></button>
      <nav id="main-navigation" className={open ? 'navigation is-open' : 'navigation'} aria-label="ניווט ראשי" onKeyDown={event => {
        if (event.key === 'Escape') { setOpen(false); document.querySelector<HTMLButtonElement>('.menu-toggle')?.focus() }
      }}>
        {navigation.map((item, index) => <a key={item.href} href={item.href} className={index === activeIndex ? 'nav-home' : undefined} aria-current={index === activeIndex ? 'page' : undefined} onClick={() => setOpen(false)}>{item.label}</a>)}
      </nav>
    </div>
  </header>
}

function Wave({ position, variant = 'gentle' }: { position: 'top' | 'bottom'; variant?: 'gentle' | 'rolling' }) {
  return <svg className={`wave wave-${position}`} viewBox="0 0 1440 65" preserveAspectRatio="none" aria-hidden="true"><path d={variant === 'rolling'
    ? 'M0 30C160-20 320 70 540 46S880 0 1080 24s250 28 360 0V65H0Z'
    : 'M0 47Q720-26 1440 47V65H0Z'} /></svg>
}

function Hero() {
  return <section className="hero" id="home" aria-labelledby="hero-title">
    <div className="hero-backdrop" aria-hidden="true" />
    <div className="hero-copy">
      <img className="hero-brand" src="/assets/fca-road-logo.webp" alt="Family Car Agent" width="2048" height="682" />
      <h1 id="hero-title">הדרך החכמה לנהל את הרכב המשפחתי</h1>
      <p>ניהול רכבים, הזמנות ותיאום בין בני המשפחה — במקום אחד.</p>
      <div className="hero-actions">
        <a className="button button-primary" href="#download"><Icon name="download" />הורדת האפליקציה</a>
      </div>
    </div>
    <img className="hero-illustration" src="/assets/family-road.webp" alt="משפחה במכונית על כביש מתפתל, בין עצים ועננים" width="1672" height="941" />
  </section>
}

const features: { title: string; description: ReactNode; icon: IconName; color: string }[] = [
  { title: 'ניהול רכבים', description: <>כל רכבי המשפחה<br />במקום אחד</>, icon: 'car', color: 'blue' },
  { title: 'הזמנת רכב', description: <>תיאום ושמירת זמן<br />שימוש בקלות</>, icon: 'calendar', color: 'cream' },
  { title: 'תיאום משפחתי', description: <>תכנון משותף, שקוף ופשוט<br />לכל בני המשפחה</>, icon: 'family', color: 'mint' },
  { title: 'עדכונים והתראות', description: <>הודעות חשובות בזמן אמת<br />על הזמנות ושינויים</>, icon: 'bell', color: 'blue' },
]
function Capabilities() {
  return <section className="capabilities blue-band" id="capabilities" aria-labelledby="capabilities-title">
    <Wave position="top" variant="rolling" />
    <div className="section-inner">
      <h2 id="capabilities-title" className="ruled-title">מה אפשר לעשות עם Family Car Agent?</h2>
      <div className="feature-grid">{features.map(feature => <article className="feature-card" key={feature.title}>
        <span className={`icon-disc ${feature.color}`}><Icon name={feature.icon} /></span>
        <h3>{feature.title}</h3><p>{feature.description}</p>
      </article>)}</div>
    </div>
    <Wave position="bottom" />
  </section>
}

// Decorative geometry reconstructed from the approved mockup. FCA artwork remains an original image.
function PhoneIllustration() {
  return <svg className="phone-illustration" viewBox="0 0 340 260" aria-hidden="true">
    <g fill="#b5d0b9"><ellipse cx="80" cy="176" rx="22" ry="76" transform="rotate(-27 80 176)" /><ellipse cx="65" cy="220" rx="20" ry="59" transform="rotate(-40 65 220)" /><ellipse cx="268" cy="205" rx="24" ry="78" transform="rotate(37 268 205)" /></g>
    <g stroke="#96b69e" strokeWidth="3" fill="none"><path d="m66 136 56 124m170-69-45 69" /></g>
    <g transform="rotate(-7 178 146)"><rect x="109" y="20" width="140" height="270" rx="25" fill="#fffcf6" stroke="#102e43" strokeWidth="6" /><path d="M148 22h65v8a8 8 0 0 1-8 8h-49a8 8 0 0 1-8-8Z" fill="#102e43" /><image href="/assets/fca-app-icon.webp" x="125" y="84" width="110" height="110" /><path d="M105 72v25" stroke="#102e43" strokeWidth="5" strokeLinecap="round" /></g>
    <g stroke="#102e43" strokeWidth="5" strokeLinecap="round"><path d="m272 36 10-15m0 32 18-5m-20 20 15 6" /></g>
  </svg>
}
function StoreBadge({ store }: { store: 'apple' | 'google' }) {
  return <button className="store-badge" disabled aria-label={`${store === 'apple' ? 'App Store' : 'Google Play'} — קישור ההורדה יתווסף בהמשך`} title="קישור ההורדה יתווסף בהמשך">
    {store === 'apple' ? <svg viewBox="0 0 24 28" aria-hidden="true"><path d="M17 4c1.3-1.6 1.2-3 1.2-3s-2 .1-3.3 1.6c-1.3 1.4-1.2 3-1.2 3s1.8.2 3.3-1.6ZM20.4 15.3c0-3 2.5-4.5 2.6-4.6-1.4-2.1-3.6-2.4-4.4-2.4-1.9-.2-3.7 1.1-4.7 1.1-1 0-2.5-1.1-4.1-1.1-2.1 0-4.1 1.2-5.2 3-2.2 3.8-.6 9.5 1.5 12.5 1 1.5 2.1 3.1 3.7 3 1.5 0 2.1-1 4-1 1.8 0 2.4 1 4 1 1.7 0 2.7-1.5 3.7-3 .9-1.3 1.4-2.6 1.6-3.2-.1 0-2.7-1.1-2.7-5.3Z" /></svg>
      : <svg viewBox="0 0 30 34" aria-hidden="true"><path fill="#37c6ed" d="M1 1v32l17-16Z" /><path fill="#51d68a" d="m1 1 21 12-4 4Z" /><path fill="#ffcf46" d="m22 13 6 3q2 1 0 2l-6 3-4-4Z" /><path fill="#f45b69" d="M1 33 22 21l-4-4Z" /></svg>}
    <span><small>{store === 'apple' ? 'Download on the' : 'GET IT ON'}</small><strong>{store === 'apple' ? 'App Store' : 'Google Play'}</strong></span>
  </button>
}
function Downloads() {
  return <section className="downloads section-inner" id="download" aria-labelledby="download-title">
    <div className="download-copy"><h2 id="download-title">Family Car Agent תמיד איתכם</h2>
      <p>הורידו את האפליקציה למכשיר שלכם והצטרפו למשפחות<br className="desktop-break" /> שכבר מנהלות את הרכב המשפחתי בצורה חכמה יותר.</p>
      <div className="store-badges"><StoreBadge store="apple" /><StoreBadge store="google" /></div>
      <p className="availability">קישורי ההורדה יתווספו בהמשך.</p>
    </div><PhoneIllustration />
  </section>
}
function Support() {
  return <section className="support blue-band" id="support" aria-labelledby="support-title">
    <Wave position="top" variant="rolling" />
    <div className="section-inner"><h2 id="support-title" className="spark-title">צריכים עזרה?<span className="spark" aria-hidden="true"><i /><i /><i /></span></h2>
      <p>אנחנו כאן כדי לעזור, עם מדריכים, פתרונות ויצירת קשר ישירה.</p>
      <div className="support-grid">
        <div className="support-card"><span className="icon-disc blue"><Icon name="book" /></span><span><strong><a className="home-support-link" href="/support">מרכז התמיכה</a></strong><span>מדריכים, הסברים ופתרון בעיות</span></span></div>
        <a className="support-card" id="contact" href="/contact"><span className="icon-disc mint"><Icon name="mail" /></span><span><strong>יצירת קשר</strong><span>שליחת פנייה לצוות התמיכה</span></span></a>
      </div>
    </div><Wave position="bottom" variant="rolling" />
  </section>
}
function FAQ() {
  return <section className="faq section-inner" aria-labelledby="faq-title"><h2 id="faq-title" className="ruled-title">שאלות נפוצות</h2>
    <SharedFAQ />
  </section>
}
function Footer() {
  return <footer className="site-footer"><Wave position="top" variant="rolling" /><div className="footer-inner section-inner">
    <p dir="ltr">© 2026 Family Car Agent</p><nav aria-label="קישורים בתחתית האתר"><a href="/terms">תנאי שימוש</a><span aria-hidden="true">|</span><a href="/privacy">מדיניות פרטיות</a><span aria-hidden="true">|</span><a href="/contact">יצירת קשר</a></nav>
    <img src="/assets/fca-road-logo-white.svg" alt="Family Car Agent" width="2170" height="725" />
  </div></footer>
}
export default function App({ pathname }: { pathname?: string } = {}) {
  const [browserPath, setBrowserPath] = useState(() => typeof window === 'undefined' ? '/' : window.location.pathname)
  useEffect(() => {
    const update = () => setBrowserPath(window.location.pathname)
    window.addEventListener('popstate', update)
    return () => window.removeEventListener('popstate', update)
  }, [])
  const route = (pathname ?? browserPath).replace(/\/+$/, '')
  useEffect(() => { applyPageMetadata(document, route) }, [route])
  const features = route === '/features'
  const familyGuides = route === '/support/family'
  const createGuide = route === '/support/family/create'
  const joinGuide = route === '/support/family/join'
  const manageGuide = route === '/support/family/manage'
  const settingsListing = route === '/support/settings'
  const settingsGuide = settingsGuides.find(guide => guide.path === route)
  const bookingListing = route === '/support/bookings'
  const bookingGuide = bookingGuides.find(guide => guide.path === route)
  const vehicleListing = route === '/support/vehicles'
  const vehicleGuide = vehicleGuides.find(g => g.path === route)
  const support = route === '/support' || familyGuides || createGuide || joinGuide || manageGuide || settingsListing || !!settingsGuide || bookingListing || !!bookingGuide || vehicleListing || !!vehicleGuide
  const contact = route === '/contact'
  const legal = route === '/terms' || route === '/privacy'
  const missing = route !== '' && !features && !support && !contact && !legal
  return <><a className="skip-link" href="#main">דילוג לתוכן</a><Header activeIndex={missing || legal ? -1 : contact ? 3 : support ? 2 : features ? 1 : 0} /><main id="main">{legal ? <LegalPage document={route === '/terms' ? 'terms' : 'privacy'} /> : missing ? <NotFoundPage /> : vehicleGuide ? <VehicleGuidePage guide={vehicleGuide} /> : vehicleListing ? <VehicleGuidesPage /> : bookingGuide ? <GuidePage {...bookingGuide} /> : bookingListing ? <BookingGuidesPage /> : settingsGuide ? <GuidePage {...settingsGuide} /> : settingsListing ? <SettingsGuidesPage /> : manageGuide ? <GuidePage {...manageFamilyGuide} /> : joinGuide ? <GuidePage {...joinFamilyGuide} /> : createGuide ? <GuidePage {...createFamilyGuide} /> : familyGuides ? <FamilyGuidesPage /> : contact ? <ContactPage /> : support ? <SupportPage /> : features ? <FeaturesPage badges={<><StoreBadge store="apple" /><StoreBadge store="google" /></>} /> : <><Hero /><Capabilities /><Downloads /><Support /><FAQ /></>}</main><Footer /></>
}

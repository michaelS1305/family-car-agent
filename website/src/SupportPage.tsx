import SharedFAQ from './SharedFAQ'
import './SupportPage.css'

const categories=[['car','ניהול רכבים','הוספה, עדכון פרטים וחיבור לאפליקציה.'],['calendar','הזמנת רכב','יצירה, שינוי וביטול הזמנות.'],['family','ניהול משפחה','הוספה, הזמנה, הרשאות ותפקידים.'],['bell','הגדרות והתראות','ניהול העדפות, התראות והרשאות.']] as const
export function SupportIcon({kind}:{kind:string}) {
 return <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
 {kind==='car'?<><path d="m8 20 4-12h24l4 12M7 34v7m34-7v7M5 22q0-4 4-4h30q4 0 4 4v12H5Z"/><path d="M12 25h3m18 0h3M16 32h16"/></>:kind==='calendar'?<><rect x="7" y="10" width="34" height="32" rx="3"/><path d="M15 5v11m18-11v11M7 21h34"/></>:kind==='family'?<><circle cx="24" cy="11" r="6"/><circle cx="9" cy="19" r="4"/><circle cx="39" cy="19" r="4"/><path d="M12 42V33a12 12 0 0 1 24 0v9M2 39v-8a7 7 0 0 1 9-6m26 0a7 7 0 0 1 9 6v8"/></>:kind==='bell'?<><path d="M8 35c4-4 4-6 4-15a12 12 0 0 1 24 0c0 9 0 11 4 15v3H8ZM20 44h8M24 4V1"/></>:kind==='headset'?<><path d="M7 27v-6a17 17 0 0 1 34 0v6M39 35q-3 10-15 8"/><rect x="3" y="23" width="8" height="14" rx="4" fill="currentColor"/><rect x="37" y="23" width="8" height="14" rx="4" fill="currentColor"/><path d="M23 43h5" strokeWidth="5"/></>:kind==='bulb'?<><path d="M17 34v-4c-15-12-7-25 7-25s22 13 7 25v4ZM18 39h12m-9 5h6M24 0v-3"/><path d="M17 13q4-5 10-3"/></>:<path d="m4 22 39-17-12 37-9-14-18-6Zm18 6L43 5M22 28v13l7-6"/>}
 </svg>
}
export function Envelope() {
 return <svg className="support-envelope" viewBox="0 0 300 150" aria-hidden="true"><g fill="#b6d6b8"><ellipse cx="42" cy="128" rx="12" ry="28" transform="rotate(-30 42 128)"/><ellipse cx="63" cy="118" rx="13" ry="34" transform="rotate(12 63 118)"/><ellipse cx="235" cy="107" rx="19" ry="47" transform="rotate(22 235 107)"/><ellipse cx="254" cy="126" rx="13" ry="29" transform="rotate(32 254 126)"/></g><g transform="rotate(-12 155 75)" fill="#fff" stroke="#102d43" strokeWidth="5" strokeLinejoin="round"><rect x="87" y="31" width="133" height="81" rx="3"/><path d="m89 33 65 49 64-48" fill="none"/></g><path d="m58 51 20 3m-27 21 24-2m-13 24 17-5" stroke="#102d43" strokeWidth="4" strokeLinecap="round"/></svg>
}
export default function SupportPage() {
 return <div className="support-page">
 <section className="support-hero" aria-labelledby="support-heading"><div className="support-hero-copy"><div className="support-heading"><SupportIcon kind="headset"/><h1 id="support-heading">מרכז התמיכה</h1></div><p>כאן תמצאו תשובות לשאלות נפוצות ומדריכים לכל נושא באפליקציה.</p></div><img src="/assets/family-road.webp" alt="משפחה במכונית על כביש מתפתל" width="1672" height="941"/></section>
 <section className="support-topics section-inner" aria-labelledby="topics-heading"><h2 id="topics-heading" className="ruled-title">בחרו נושא שתרצו לקבל עליו הסבר</h2><div className="support-topics-grid">{categories.map(([kind,title,description])=><article key={kind} className={`support-topic topic-${kind}`}><span className="topic-icon"><SupportIcon kind={kind}/></span><h3>{kind === 'family' ? <a href="/support/family">{title}</a> : kind === 'bell' ? <a href="/support/settings">{title}</a> : kind === 'calendar' ? <a href="/support/bookings">{title}</a> : kind === 'car' ? <a href="/support/vehicles">{title}</a> : title}</h3><p>{description}</p></article>)}</div></section>
 <aside className="support-tip section-inner"><span className="tip-icon"><SupportIcon kind="bulb"/></span><h2>טיפ חשוב</h2><p>כדאי לוודא שחיבור והזיהוי מוגדרים כמו שצריך, לקבלת עדכונים לייב והיסטוריית שימושים.</p></aside>
 <section className="faq support-faq section-inner" aria-labelledby="support-faq-title"><h2 id="support-faq-title">שאלות ותשובות</h2><SharedFAQ/></section>
 <section className="support-contact section-inner" aria-labelledby="contact-heading"><div><h2 id="contact-heading">לא מצאתם מענה?</h2><p>אנחנו כאן לעזור. פנו אלינו ונחזור אליכם בהקדם.</p></div><div className="contact-action"><a className="button button-primary" href="/contact"><SupportIcon kind="send"/>יצירת קשר</a></div><Envelope/></section>
 </div>
}

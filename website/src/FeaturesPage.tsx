import type { ReactNode } from 'react'
import './FeaturesPage.css'

export const capabilities = [
  {title:'ניהול משפחתי משותף', description:'ניהול בני המשפחה והרכבים, חלוקת השימוש ותיאום פשוט ונוח בין כולם.', kind:'family'},
  {title:'עדכונים בזמן אמת', description:'חיבור וזיהוי אוטומטי, מידע חי על מי משתמש ברכב, מתי יצא ומתי חזר – עם היסטוריית שימושים מלאה.', kind:'live'},
  {title:'טיפולים ותחזוקה', description:'קביעת טיפולים, מעקב אחר מועדים והיסטוריה מסודרת לכל רכב.', kind:'maintenance'},
] as const

// Decorative vectors reconstructed from the supplied capabilities mockup.
function Car({family=false}:{family?:boolean}) {
  return <g fill="#f5fbff" stroke="#102d43" strokeWidth="5" strokeLinejoin="round" strokeLinecap="round">
    {family && <g fill="none"><circle cx="65" cy="12" r="10"/><circle cx="42" cy="21" r="8"/><circle cx="88" cy="21" r="8"/><path d="M47 46v-8a18 18 0 0 1 36 0v8M26 44a15 15 0 0 1 22-14m34 0a15 15 0 0 1 22 14"/></g>}
    <path d="M9 72 30 62 45 46q7-5 19-5h18q7 0 13 6l18 17 17 5q10 4 10 13v10H8q-8 0-6-9Z"/><path d="M44 58h44"/><circle cx="30" cy="94" r="12"/><circle cx="112" cy="94" r="12"/>
  </g>
}
function FamilyMark() { return <svg viewBox="0 0 120 100" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="5" strokeLinecap="round"><circle cx="60" cy="22" r="13"/><circle cx="25" cy="35" r="10"/><circle cx="95" cy="35" r="10"/><path d="M34 88V75a26 26 0 0 1 52 0v13M8 85V69a17 17 0 0 1 25-15m54 0a17 17 0 0 1 25 15v16"/></svg> }
function Wrench() {return <path d="m36 75 39-40a19 19 0 0 1 24-25L87 22l9 9 12-12a19 19 0 0 1-25 24L44 83q-8 7-13 1t5-9Z"/>}
function Symbol({kind}:{kind:typeof capabilities[number]['kind']}) {
  if(kind==='family') return <FamilyMark/>
  return <svg viewBox="0 0 120 100" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="5" strokeLinejoin="round" strokeLinecap="round">{kind==='live'?<><rect x="24" y="65" width="11" height="25" rx="2"/><rect x="46" y="49" width="11" height="41" rx="2"/><rect x="68" y="32" width="11" height="58" rx="2"/><rect x="90" y="14" width="11" height="76" rx="2"/></>:<Wrench/>}</svg>
}
function HeroArt() {
 return <svg className="features-hero-art" viewBox="0 0 1024 510" aria-hidden="true">
  <defs><linearGradient id="cap-road"><stop stopColor="#e8f6ff"/><stop offset="1" stopColor="#d6edfc"/></linearGradient><linearGradient id="cap-leaf"><stop stopColor="#c8e6cf"/><stop offset="1" stopColor="#9bcbae"/></linearGradient></defs>
  <g fill="url(#cap-leaf)"><ellipse cx="105" cy="357" rx="33" ry="100" transform="rotate(-33 105 357)"/><ellipse cx="86" cy="412" rx="30" ry="70" transform="rotate(-53 86 412)"/><ellipse cx="320" cy="358" rx="32" ry="112" transform="rotate(25 320 358)"/><ellipse cx="347" cy="410" rx="25" ry="76" transform="rotate(42 347 410)"/></g>
  <g stroke="#9ac9aa" strokeWidth="3"><path d="m68 322 90 144m196-150-56 150"/></g>
  <g transform="rotate(-14 222 280)"><rect x="125" y="74" width="198" height="380" rx="37" fill="#eff8ff" stroke="#102d43" strokeWidth="8"/><path d="M185 77h80v12q0 12-12 12h-56q-12 0-12-12Z" fill="#102d43"/><g transform="translate(160 139) scale(.85)"><Car family/></g>{[0,1,2].map(n=><g key={n} transform={`translate(150 ${270+n*53})`}><rect width="150" height="45" rx="19" fill="white"/><rect x="10" y="10" width="91" height="26" rx="10" fill="#bee6fc"/><circle cx="126" cy="22" r="15" fill="#abe0c0"/><path d="m120 22 5 5 8-13" stroke="#102d43" strokeWidth="4" fill="none" strokeLinecap="round"/></g>)}</g>
  <g fill="#bfe8ff"><path d="M26 213q0-12 14-12 10-27 27-5 20-3 20 17Z"/><path d="M411 371q0-12 14-12 10-27 27-5 20-3 20 17Z"/></g>
  <g stroke="#102d43" strokeWidth="4" strokeLinecap="round"><path d="m309 94 15-24m-6 39 27-13m-23 26 25 2"/></g>
  <path d="M843 452q102-76 181-3v33H812Z" fill="#fdf4e6"/>
  <g fill="#b4dbbc"><ellipse cx="912" cy="405" rx="18" ry="30"/><ellipse cx="955" cy="417" rx="13" ry="23"/></g><path d="M912 428v18m43-10v17" stroke="#9aafbc" strokeWidth="6" strokeLinecap="round"/>
  <path d="M-30 510Q137 427 348 457T808 461Q925 424 813 418" stroke="url(#cap-road)" strokeWidth="56" fill="none" strokeLinecap="round"/><path d="M459 488q201 13 350-18t8-52" fill="none" stroke="#95bdd8" strokeWidth="6" strokeLinecap="round" strokeDasharray="28 39"/>
  <g transform="translate(520 362)"><Car/></g><g transform="translate(700 390) scale(.65)"><Car/></g>
 </svg>
}
function DetailArt({kind}:{kind:typeof capabilities[number]['kind']}) {
 return <svg className="capability-art" viewBox="0 0 300 170" aria-hidden="true">
  {kind==='family'?<><g transform="translate(90 54)"><Car/></g><g fill="none" stroke="#80cca1" strokeWidth="9" strokeLinecap="round"><path d="M177 29q34-31 68 0m-53 16q19-18 38 0"/></g><circle cx="211" cy="59" r="8" fill="#80cca1"/><path d="M21 112h45m-29 17h29" stroke="#98b8cb" strokeWidth="5" strokeLinecap="round"/></>:kind==='live'?<><path d="M40 118q8-38 69-38" fill="none" stroke="#85cba0" strokeWidth="7" strokeLinecap="round"/><path d="M114 80q80-1 42 22t90 16" fill="none" stroke="#96b9d1" strokeWidth="6" strokeLinecap="round"/><path d="M211 50c-36 0-22 34 0 58 22-24 36-58 0-58Z" fill="white" stroke="#102d43" strokeWidth="6"/><circle cx="211" cy="68" r="9" fill="#9ad7b1"/></>:<><rect x="87" y="38" width="109" height="89" rx="12" fill="white" stroke="#102d43" strokeWidth="6"/><path d="M90 59h103" stroke="#adddc2" strokeWidth="12"/><path d="M111 29v18m60-18v18" stroke="#102d43" strokeWidth="8" strokeLinecap="round"/>{[0,1,2,3].map(n=><rect key={n} x={104+n%2*25} y={76+Math.floor(n/2)*23} width="13" height="13" rx="3" fill="#b4dfc4"/>)}<circle cx="198" cy="116" r="34" fill="#b4dfc4"/><g transform="translate(165 82) scale(.55)" fill="none" stroke="#102d43" strokeWidth="6" strokeLinejoin="round"><Wrench/></g><path d="m215 35 12-22m-2 35 25-11m-21 26 25-1" stroke="#102d43" strokeWidth="4" strokeLinecap="round"/></>}
 </svg>
}
export default function FeaturesPage({badges}:{badges:ReactNode}) {
 return <div className="features-page">
  <section className="features-hero" aria-labelledby="features-heading"><div className="features-intro"><span className="features-eyebrow">יכולות האפליקציה</span><h1 id="features-heading">סוכן חכם לניהול הרכבים<br/> של המשפחה</h1><p>כל מה שהמשפחה צריכה כדי לנהל יחד את הרכבים, השימוש, התחזוקה והמידע – במקום אחד.</p></div><HeroArt/></section>
  <div className="capability-sections">{capabilities.map(({title,description,kind})=><section className={`capability-row capability-${kind}`} key={kind} aria-labelledby={`cap-${kind}`}><div className="capability-inner"><div className="capability-symbol"><Symbol kind={kind}/></div><div className="capability-copy"><h2 id={`cap-${kind}`}>{title}</h2><p>{description}</p></div><DetailArt kind={kind}/></div></section>)}</div>
  <section className="features-download" aria-labelledby="features-download-title"><div className="features-badges">{badges}</div><h2 id="features-download-title">מוכנים לנהל את הרכב<br/> של המשפחה בצורה חכמה?</h2><img src="/assets/family-road.webp" alt="משפחה במכונית על כביש מתפתל" width="1672" height="941"/></section>
 </div>
}

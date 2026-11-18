import { useId, useState } from 'react'
import { faqEntries } from './faqData'
import './SharedFAQ.css'

export default function SharedFAQ() {
 const [expanded,setExpanded]=useState(false)
 const id=useId()
 const entry=(item:typeof faqEntries[number],index:number)=><details key={index}><summary>{item.question}<svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg></summary><div className="faq-answer">{item.answer.split('\n\n').map((paragraph,i)=><p key={i}>{paragraph.split(/(\*\*.*?\*\*)/g).map((part,j)=>part.startsWith('**')?<strong key={j}>{part.slice(2,-2)}</strong>:part)}</p>)}</div></details>
 return <><div className="faq-list">{faqEntries.slice(0,4).map(entry)}</div><div id={id} className="faq-list faq-extra" hidden={!expanded}>{expanded && faqEntries.slice(4).map((item,i)=>entry(item,i+4))}</div><div className="faq-more"><button type="button" aria-expanded={expanded} aria-controls={id} onClick={()=>setExpanded(!expanded)}>{expanded?'הצג פחות':'הצג עוד'}</button></div></>
}

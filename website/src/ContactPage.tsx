import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Envelope, SupportIcon } from './SupportPage'
import { addAttachments, attachmentAccept, contactSubjects, removeAttachment, submissionUnavailable, validateContact } from './contactForm'
import type { ContactDraft, ContactErrors } from './contactForm'
import { ContactSubmission, contactEndpoint } from './contactSubmission'
import ContactTurnstile from './ContactTurnstile'
import './ContactPage.css'

export default function ContactPage() {
 const [draft,setDraft]=useState<ContactDraft>({name:'',email:'',subject:'',description:''})
 const [files,setFiles]=useState<File[]>([])
 const [errors,setErrors]=useState<ContactErrors>({})
 const [fileError,setFileError]=useState('')
 const [notice,setNotice]=useState('')
 const [token,setToken]=useState('')
 const [busy,setBusy]=useState(false)
 const [resetVersion,setResetVersion]=useState(0)
 const [retryUntil,setRetryUntil]=useState(0)
 const [now,setNow]=useState(Date.now())
 const submission=useRef(new ContactSubmission())
 const endpoint=contactEndpoint(import.meta.env.VITE_CONTACT_API_BASE_URL??'')
 const sitekey=import.meta.env.VITE_TURNSTILE_SITE_KEY??''
 const configured=!!endpoint && !!sitekey
 useEffect(()=>{if(!retryUntil) return;const timer=setInterval(()=>setNow(Date.now()),1000);return ()=>clearInterval(timer)},[retryUntil])
 const formRef=useRef<HTMLFormElement>(null)
 function update(key:keyof ContactDraft,value:string) {
  setDraft(old=>({...old,[key]:value})); setErrors(old=>({...old,[key]:undefined})); setNotice('')
 }
 async function submit(event:FormEvent<HTMLFormElement>) {
  event.preventDefault()
  if(submission.current.busy || Date.now()<submission.current.retryUntil) return
  const nextErrors=validateContact(draft)
  setErrors(nextErrors)
  if(Object.keys(nextErrors).length) {
   setNotice('יש להשלים את השדות המסומנים. הפנייה לא נשלחה.')
   formRef.current?.querySelector<HTMLElement>(`[name="${Object.keys(nextErrors)[0]}"]`)?.focus()
   return
  }
  if(!endpoint || !sitekey) {setNotice(submissionUnavailable);return}
  setNotice('')
  setBusy(true)
  try {
   const result=await submission.current.submit(endpoint,draft,files,token,
    ()=>{setToken('');setResetVersion(value=>value+1)},
    ()=>{setDraft({name:'',email:'',subject:'',description:''});setFiles([]);setFileError('')})
   if(result) {
    setNotice(result.message+(result.requestId?` מספר פנייה לבדיקה: ${result.requestId}`:''))
    setRetryUntil(result.retryUntil??0);setNow(Date.now())
   }
  } finally {setBusy(false)}
 }
 const fieldError=(key:keyof ContactDraft)=>errors[key]?<p className="contact-error" id={`${key}-error`}>{errors[key]}</p>:null
 return <div className="contact-page">
  <section className="contact-hero" aria-labelledby="contact-title"><div className="contact-hero-copy"><div className="contact-title-row"><span><svg viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="3" aria-hidden="true"><rect x="5" y="10" width="38" height="28" rx="3"/><path d="m6 12 18 13 18-13"/></svg></span><h1 id="contact-title">יצירת קשר</h1></div><p>יש שאלה, בעיה או רעיון לשיפור?<br/>אנחנו כאן כדי לעזור.</p></div><Envelope/><img className="contact-hero-road" src="/assets/family-road.webp" alt="" width="1672" height="941"/><span className="contact-cloud cloud-one"/><span className="contact-cloud cloud-two"/></section>
  <div className="contact-columns section-inner">
   <form className="contact-form" ref={formRef} onSubmit={submit} noValidate aria-busy={busy} aria-labelledby="contact-form-title">
    <h2 id="contact-form-title"><SupportIcon kind="headset"/>פתיחת פנייה לתמיכה</h2>
    <fieldset className="contact-fields" disabled={busy}><div className="contact-field"><label htmlFor="full-name">שם מלא <span aria-hidden="true">*</span></label><input id="full-name" name="name" autoComplete="name" required placeholder="הזינו שם מלא" value={draft.name} onChange={e=>update('name',e.target.value)} onBlur={()=>setDraft(old=>({...old,name:old.name.trim()}))} aria-invalid={!!errors.name} aria-describedby={errors.name?'name-error':undefined}/>{fieldError('name')}</div>
    <div className="contact-field"><label htmlFor="email">כתובת דוא״ל <span aria-hidden="true">*</span></label><input id="email" name="email" type="email" autoComplete="email" dir="ltr" required placeholder="name@example.com" value={draft.email} onChange={e=>update('email',e.target.value)} onBlur={()=>setDraft(old=>({...old,email:old.email.trim()}))} aria-invalid={!!errors.email} aria-describedby={errors.email?'email-error':undefined}/>{fieldError('email')}</div>
    <div className="contact-field"><label htmlFor="subject">נושא הפנייה <span aria-hidden="true">*</span></label><select id="subject" name="subject" required value={draft.subject} onChange={e=>update('subject',e.target.value)} aria-invalid={!!errors.subject} aria-describedby={errors.subject?'subject-error':undefined}><option value="" disabled>בחרו נושא</option>{contactSubjects.map(subject=><option key={subject} value={subject}>{subject}</option>)}</select>{fieldError('subject')}</div>
    <div className="contact-field"><label htmlFor="description">תיאור הפנייה <span aria-hidden="true">*</span></label><textarea id="description" name="description" required rows={5} placeholder="פרטו בקצרה את השאלה או הבעיה..." value={draft.description} onChange={e=>update('description',e.target.value)} aria-invalid={!!errors.description} aria-describedby={`description-count${errors.description?' description-error':''}`}/><span id="description-count" className="description-count" dir="ltr">{[...draft.description.trim()].length} / 1,000</span>{fieldError('description')}</div>
    <div className="attachment-zone"><label htmlFor="attachments"><svg viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="3" aria-hidden="true"><path d="M32 9H8v32h32V22M9 34l10-11 8 7 6-6 7 8M39 3v14m-7-7h14"/></svg><span><strong>צירוף קבצים</strong> (לא חובה)</span></label><p id="attachment-help">תמונות או מסמכי PDF (עד 5 קבצים, עד 5MB לכל קובץ, עד 10MB בסך הכול; MB הוא מיליון בתים)</p><input type="file" id="attachments" multiple accept={attachmentAccept} aria-describedby={`attachment-help${fileError?' attachment-error':''}`} aria-invalid={!!fileError} onChange={event=>{const result=addAttachments(files,Array.from(event.target.files??[]));setFiles(result.files);setFileError(result.error??'');setNotice('');event.target.value=''}}/>{fileError && <p role="alert" id="attachment-error" className="contact-error">{fileError}</p>}</div>
    {files.length>0 && <ul className="attachment-list" aria-label="קבצים שנבחרו">{files.map((file,index)=><li key={`${file.name}-${index}`}><span><bdi>{file.name}</bdi><small dir="ltr">{(file.size/1_000_000).toFixed(2)} MB</small></span><button type="button" onClick={()=>{setFiles(old=>removeAttachment(old,index));setFileError('');setNotice('')}} aria-label={`הסרת ${file.name}`}>הסרה</button></li>)}</ul>}
    </fieldset>
    {configured?<ContactTurnstile sitekey={sitekey} onToken={setToken} resetVersion={resetVersion}/>:<p className="contact-prototype">{submissionUnavailable}</p>}
    {retryUntil>now && <p className="contact-notice">ניתן לנסות שוב בעוד {Math.ceil((retryUntil-now)/1000)} שניות.</p>}
    <button className="button button-primary contact-submit" type="submit" disabled={busy || !configured || !token || retryUntil>now}><SupportIcon kind="send"/>{busy?'שולחים…':'שליחת פנייה'}</button>
    <p className="contact-notice" role="status" aria-live="polite">{notice}</p>
   </form>
   <aside className="contact-information" aria-labelledby="other-contact-title"><h2 id="other-contact-title">דרכי קשר נוספות</h2><div className="contact-email-block"><h3>דוא״ל תמיכה</h3><a dir="ltr" href="mailto:support@familycaragent.com">support@familycaragent.com</a></div><div className="contact-info-note"><h3>פנייה בדוא״ל</h3><p>ניתן לפנות אלינו בכתובת התמיכה שלמעלה.</p></div><img src="/assets/family-road.webp" alt="משפחה במכונית על כביש מתפתל" width="1672" height="941"/></aside>
  </div>
 </div>
}

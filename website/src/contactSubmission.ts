import { addAttachments, validateContact } from './contactForm'
import type { ContactDraft } from './contactForm'

export type ContactResult = { kind: 'accepted'|'invalid'|'limited'|'unavailable'|'uncertain'|'verification'; message: string; retryUntil?: number; requestId?: string }
const uncertain: ContactResult = {kind:'uncertain',message:'לא ניתן לאשר את מצב השליחה. ייתכן שהפנייה נשלחה. הפרטים נשמרו; אין צורך לשלוח שוב אוטומטית. ניתן לברר בדוא״ל התמיכה.'}
export function contactEndpoint(base: string): string | null {
 try {
  const url=new URL(base)
  if(url.username || url.password || url.search || url.hash || (url.protocol!=='https:' && !(url.protocol==='http:' && ['localhost','127.0.0.1','[::1]'].includes(url.hostname)))) return null
  return url.href.replace(/\/$/,'')+'/api/contact'
 } catch { return null }
}
export function retryDeadline(value: string|null, now=Date.now()): number {
 // Cross-origin responses currently do not expose Retry-After. The server's
 // largest quota window is 3601 seconds; use that conservative fallback.
 if(value && /^\d+$/.test(value)) return now+Number(value)*1000
 const date=value?Date.parse(value):NaN
 return Number.isFinite(date)?Math.max(now,date):now+3601_000
}
export async function sendContact(endpoint: string, draft: ContactDraft, files: File[], token: string, fetcher: typeof fetch=fetch, timeoutMs=90_000): Promise<ContactResult> {
 const body=new FormData()
 for(const key of ['name','email','subject','description'] as const) body.append(key,draft[key].trim())
 body.append('turnstile_token',token)
 files.forEach(file=>body.append('attachments',file,file.name))
 const controller=new AbortController()
 const timer=setTimeout(()=>controller.abort(),timeoutMs)
 try {
  const response=await fetcher(endpoint,{method:'POST',body,credentials:'omit',redirect:'error',signal:controller.signal})
  const payload: unknown=await response.json().catch(()=>null)
  const data=payload && typeof payload==='object'?payload as Record<string,unknown>:{}
  const requestId=typeof data.request_id==='string' && /^[a-f0-9]{32}$/.test(data.request_id)?data.request_id:undefined
  let result: ContactResult
  if(response.status===200 && data.code==='accepted') result={kind:'accepted',message:'הפנייה התקבלה לשליחה בדוא״ל. אין בכך אישור שהגיעה לתיבת התמיכה.'}
  else if(data.code==='delivery_uncertain') result=uncertain
  else if(response.status===429) result={kind:'limited',message:'בוצעו יותר מדי ניסיונות. יש להמתין לפני ניסיון נוסף.',retryUntil:retryDeadline(response.headers.get('Retry-After'))}
  else if(data.code==='verification_failed') result={kind:'verification',message:'האימות לא הושלם. יש לבצע אימות חדש לפני השליחה.'}
  else if(response.status===422) result={kind:'invalid',message:'לא ניתן לקבל את הפרטים שנשלחו. בדקו את השדות ונסו שוב.'}
  else if(response.status===413) result={kind:'invalid',message:'הקבצים או הבקשה גדולים מדי. הקטינו את הקבצים ונסו שוב.'}
  else if(response.status===415) result={kind:'invalid',message:'סוגו או תוכנו של אחד הקבצים אינו נתמך. בחרו קובץ תקין בפורמט נתמך.'}
  else if(response.status===503 && ['service_unavailable','smtp_unavailable','verification_unavailable','request_incomplete'].includes(String(data.code))) result={kind:'unavailable',message:'השירות אינו זמין כרגע. הפרטים נשמרו; ניתן לפנות אלינו בדוא״ל התמיכה.'}
  else result=uncertain
  return {...result,requestId}
 } catch { return {...uncertain} }
 finally { clearTimeout(timer) }
}

// Synchronous latch prevents rapid clicks/Enter from racing React's render.
export class ContactSubmission {
 busy=false
 retryUntil=0
 async submit(endpoint: string, draft: ContactDraft, files: File[], token: string,
              reset: ()=>void, accepted: ()=>void, fetcher: typeof fetch=fetch): Promise<ContactResult|null> {
  if(this.busy || Date.now()<this.retryUntil) return null
  if(Object.keys(validateContact(draft)).length || addAttachments([],files).error) return {kind:'invalid',message:'יש לבדוק את הפרטים והקבצים לפני השליחה.'}
  if(!token) return {kind:'verification',message:'יש להשלים את האימות לפני השליחה.'}
  this.busy=true
  try {
   const result=await sendContact(endpoint,draft,files,token,fetcher)
   this.retryUntil=result.retryUntil??0
   if(result.kind==='accepted') accepted()
   return result
  } finally { this.busy=false; reset() }
 }
}

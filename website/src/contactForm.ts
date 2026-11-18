export const contactSubjects = ['תקלה', 'הצעה', 'חוות דעת'] as const
export const submissionUnavailable = 'השליחה המקוונת אינה זמינה כרגע. ניתן לפנות אלינו בדוא״ל התמיכה.'
export type ContactDraft = { name: string; email: string; subject: string; description: string }
export type ContactErrors = Partial<Record<keyof ContactDraft,string>>
export function validateContact(draft: ContactDraft): ContactErrors {
 const errors: ContactErrors = {}
 if (!draft.name.trim() || [...draft.name.trim()].length>100 || /[\x00-\x1f\x7f]/.test(draft.name)) errors.name='יש להזין שם מלא תקין, עד 100 תווים.'
 if (!draft.email.trim()) errors.email='יש להזין כתובת דוא״ל.'
 else if (draft.email.trim().length>254 || /[\x00-\x1f\x7f]/.test(draft.email) || !/^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$/.test(draft.email.trim())) errors.email='יש להזין כתובת דוא״ל תקינה.'
 if (!contactSubjects.some(subject=>subject===draft.subject)) errors.subject='יש לבחור נושא לפנייה.'
 if (!draft.description.trim()) errors.description='יש להזין תיאור פנייה.'
 else if ([...draft.description.trim()].length>1000) errors.description='תיאור הפנייה מוגבל ל־1,000 תווים.'
 return errors
}
export const maxAttachmentBytes=5_000_000
export const maxCombinedAttachmentBytes=10_000_000
const mimeByExtension: Record<string, readonly string[]> = {
 png:['image/png'], jpg:['image/jpeg'], jpeg:['image/jpeg'], webp:['image/webp'],
 heic:['image/heic'], pdf:['application/pdf'],
}
export const attachmentAccept='.png,.jpg,.jpeg,.webp,.heic,.pdf,image/png,image/jpeg,image/webp,image/heic,application/pdf'
export type AttachmentMetadata={name:string; size:number; type:string}
// Selection is atomic: rejected additions never erase files already selected.
export function addAttachments<T extends AttachmentMetadata>(current:T[],incoming:T[]): {files:T[];error?:string} {
 if(current.length+incoming.length>5) return {files:current,error:'ניתן לצרף עד 5 קבצים. הקבצים החדשים לא נוספו.'}
 for(const file of incoming) {
  const extension=file.name.split('.').pop()?.toLowerCase() ?? ''
  const allowed=mimeByExtension[extension]
  if(!allowed || !allowed.includes(file.type)) return {files:current,error:'ניתן לצרף רק PNG, JPEG, WebP, HEIC או PDF עם סוג קובץ מזוהה. הקבצים החדשים לא נוספו.'}
  if(file.size===0 || file.size>maxAttachmentBytes) return {files:current,error:'יש לבחור קובץ שאינו ריק, בגודל עד 5MB. הקבצים החדשים לא נוספו.'}
 }
 if([...current,...incoming].reduce((sum,file)=>sum+file.size,0)>maxCombinedAttachmentBytes) return {files:current,error:'הגודל הכולל של הקבצים מוגבל ל־10MB. הקבצים החדשים לא נוספו.'}
 return {files:[...current,...incoming]}
}
export function removeAttachment<T>(files:T[], index:number):T[] {return files.filter((_,i)=>i!==index)}

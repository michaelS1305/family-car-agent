import { useEffect, useRef, useState } from 'react'
import { loadTurnstile, mountTurnstile } from './turnstileClient'

export default function ContactTurnstile({sitekey,onToken,resetVersion}: {sitekey:string;onToken:(token:string)=>void;resetVersion:number}) {
 const container=useRef<HTMLDivElement>(null)
 const widget=useRef<ReturnType<typeof mountTurnstile>|null>(null)
 const callback=useRef(onToken)
 callback.current=onToken
 const [failed,setFailed]=useState(false)
 const [attempt,setAttempt]=useState(0)
 useEffect(()=>{
  let disposed=false
  setFailed(false)
  callback.current('')
  loadTurnstile().then(api=>{
   if(disposed || !container.current) return
   widget.current=mountTurnstile(api,container.current,sitekey,value=>{callback.current(value);if(value) setFailed(false)},()=>setFailed(true))
  }).catch(()=>{if(!disposed) setFailed(true)})
  return ()=>{disposed=true;widget.current?.remove();widget.current=null}
 },[sitekey,attempt])
 useEffect(()=>{try {widget.current?.reset()} catch {callback.current('');setFailed(true)}},[resetVersion])
 return <div className="contact-verification">
  <div ref={container} aria-label="אימות אבטחה לפני שליחה"/>
  {failed && <><p role="alert">האימות אינו זמין כרגע. לא ניתן לשלוח ללא אימות.</p><button type="button" onClick={()=>setAttempt(value=>value+1)}>ניסיון אימות נוסף</button></>}
 </div>
}

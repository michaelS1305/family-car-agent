export type Turnstile = {
 render: (element: HTMLElement, options: Record<string,unknown>)=>string
 reset: (id: string)=>void
 remove: (id: string)=>void
}
declare global { interface Window { turnstile?: Turnstile } }
let loading: Promise<Turnstile>|undefined
export function loadTurnstile(): Promise<Turnstile> {
 if(window.turnstile) return Promise.resolve(window.turnstile)
 if(loading) return loading
 loading=new Promise((resolve,reject)=>{
  const script=document.createElement('script')
  script.src='https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
  script.async=true
  const fail=()=>{clearTimeout(timer);script.remove();loading=undefined;reject(new Error('verification_unavailable'))}
  const timer=setTimeout(fail,15000)
  script.onerror=fail
  script.onload=()=>{clearTimeout(timer);if(window.turnstile) resolve(window.turnstile);else fail()}
  document.head.appendChild(script)
 })
 return loading
}
export function mountTurnstile(api: Turnstile, element: HTMLElement, sitekey: string, token: (value:string)=>void, error: ()=>void) {
 let active=true
 const clear=()=>{if(active) token('')}
 const id=api.render(element,{sitekey,language:'he',size:'flexible',theme:'light','response-field':false,
  callback:(value:string)=>{if(active) token(value)},
  'expired-callback':clear,'timeout-callback':clear,
  'error-callback':()=>{clear();if(active) error();return true}})
 return {
  reset:()=>{clear();if(active) api.reset(id)},
  remove:()=>{active=false;api.remove(id)},
 }
}

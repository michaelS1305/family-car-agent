import { useEffect, useRef, useState } from 'react'
import { DashboardCategoryIcon } from './DashboardCategoryIcon'
import { createFamilyVehicle, getFamilyVehicle, listFamilyVehicles, type FamilyVehicleStatus } from '../api/apiClient'
import { vehicleCreationSubmission } from '../vehicleCreation'

export function VehiclesScreen({ open, onBack, accessToken, refreshVersion, authUserId }: {
  open: boolean; onBack: () => void; accessToken: string; refreshVersion: number; authUserId: string
}) {
  const backButtonRef = useRef<HTMLButtonElement | null>(null)
  const [creation] = useState(() => {
    try { return vehicleCreationSubmission(sessionStorage, authUserId) }
    catch { return vehicleCreationSubmission() }
  })
  const [vehicles, setVehicles] = useState<FamilyVehicleStatus[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<FamilyVehicleStatus | null>(null)
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState(() => creation.pending()?.display_name ?? '')
  const [busy, setBusy] = useState(false)
  const [settled, setSettled] = useState('')
  const [error, setError] = useState('')
  const [saveError, setSaveError] = useState('')
  const [reload, setReload] = useState(0)
  const requestKey = `${accessToken}|${selected}|${refreshVersion}|${reload}`
  const loading = settled !== requestKey
  const [area, setArea] = useState('')
  useEffect(() => { if (open) backButtonRef.current?.focus({ preventScroll: true }) }, [open, selected, adding])
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    let active = true
    const request = selected ? getFamilyVehicle(accessToken, selected, { signal: controller.signal })
      : listFamilyVehicles(accessToken, { signal: controller.signal })
    void request.then(result => {
      if (!active) return
      setError('')
      if (Array.isArray(result)) setVehicles(result)
      else setDetail(result)
    }).catch((e: unknown) => {
      if (active) setError(e instanceof Error ? e.message : 'לא הצלחנו לטעון את הרכבים.')
    }).finally(() => { if (active) setSettled(requestKey) })
    return () => { active = false; controller.abort() }
  }, [accessToken, open, selected, refreshVersion, reload, requestKey])
  function back() {
    if (busy) return
    if (area) setArea('')
    else if (adding) { setAdding(false); setReload(v => v + 1) }
    else if (selected) setSelected(null)
    else onBack()
  }
  useEffect(() => {
    if (!open) return
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && (adding || selected || busy)) { event.stopImmediatePropagation(); event.preventDefault(); back() }
    }
    window.addEventListener('keydown', key, true)
    return () => window.removeEventListener('keydown', key, true)
  })
  async function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !name.trim()) return
    setBusy(true); setSaveError('')
    try {
      const vehicle = await creation.submit(name, request => createFamilyVehicle(accessToken, request))
      if (vehicle) { setAdding(false); setName(''); setSelected(vehicle.vehicle_ref); setArea(''); setReload(v => v + 1) }
    } catch (e) { setSaveError(e instanceof Error ? e.message : 'ההוספה לא הושלמה. נסו שוב.') }
    finally { setBusy(false) }
  }
  const status = (v: FamilyVehicleStatus) => v.in_use ? `בשימוש${v.current_driver ? ' — ' + v.current_driver : ''}` : 'פנוי'
  return (
    <section className={`category-placeholder-screen vehicles-screen${open ? ' is-open' : ''}`} dir="rtl"
      role="dialog" aria-modal="true" aria-label="רכבים" aria-hidden={!open} inert={!open}>
      <header className="dashboard-header category-placeholder-header">
        <button ref={backButtonRef} type="button" disabled={busy} onClick={back}
          aria-label={selected || adding ? 'חזרה לרכבים' : 'חזרה ללוח הבקרה'}><span aria-hidden="true">×</span></button>
        <h1>Family Car Agent</h1><span aria-hidden="true" />
      </header>
      <div className="vehicles-screen-content">
        <div className="family-screen-title vehicles-screen-title"><DashboardCategoryIcon icon="car" /><h2>רכבים</h2></div>
        {adding ? <form className="vehicle-panel" onSubmit={submit} aria-label="הוספת רכב">
          <h3>הוספת רכב למשפחה</h3>
          <label htmlFor="vehicle-name">שם הרכב</label>
          <input id="vehicle-name" autoFocus value={name} placeholder="למשל, היונדאי שלנו"
            disabled={busy || !!creation.pending()} onChange={e => setName(e.target.value)} required />
          <p>בחרו שם שיעזור לבני המשפחה לזהות את הרכב.</p>
          {saveError && <p role="alert">{saveError}</p>}
          {creation.pending() && !busy && <p>ייתכן שהרכב כבר נוסף. ניסיון חוזר משתמש באותה בקשה ואינו מוסיף רכב נוסף. אפשר לחזור לרשימה כדי לבדוק.</p>}
          <button type="submit" disabled={busy || !name.trim()}>{busy ? 'מוסיפים…' : creation.pending() ? 'ניסיון חוזר' : 'הוספת רכב'}</button>
          <button type="button" disabled={busy} onClick={back}>חזרה לרשימה</button>
          {creation.pending() && !busy && <button type="button" onClick={() => {
            creation.reset(); setSaveError(''); setName('')
          }}>התחלת בקשה חדשה במקום הקודמת</button>}
        </form> : <>
          {loading ? <p role="status">טוענים רכבים…</p> : error ? <div className="vehicle-panel" role="alert">
            <p>{error}</p><button onClick={() => setReload(v => v + 1)}>נסו שוב</button>
          </div> : selected && detail ? <VehicleDetail vehicle={detail} status={status(detail)} area={area} onArea={setArea} />
            : <div className="vehicle-list">
              {vehicles.length === 0 && <div className="vehicle-panel"><h3>הרכב הראשון שלכם מתחיל כאן</h3>
                <p>הוסיפו רכב כדי לעקוב אחר המצב שלו, ובהמשך לנהל היסטוריה, הזמנות וזיהוי אוטומטי מהטלפון.</p>
                <p>אפשר גם לחזור ולהמשיך להשתמש ב־FCA בלי להוסיף רכב עכשיו.</p></div>}
              {vehicles.map(vehicle => <button type="button" className="vehicle-panel vehicle-card" key={vehicle.vehicle_ref}
                onClick={() => { setSelected(vehicle.vehicle_ref); setArea('') }}>
                <strong>{vehicle.display_name}</strong><span>{status(vehicle)}</span>
              </button>)}
              <button className="vehicle-add" onClick={() => { setAdding(true); setSaveError('') }}>הוספת רכב</button>
            </div>}
        </>}
      </div>
    </section>
  )
}

function VehicleDetail({ vehicle, status, area, onArea }: {
  vehicle: FamilyVehicleStatus; status: string; area: string; onArea: (value: string) => void
}) {
  return <section className="vehicle-panel" aria-label="פרטי רכב">
    <h3>{vehicle.display_name}</h3><p>{status}</p>
    <div className="vehicle-actions">
      <button onClick={() => onArea('היסטוריה')}>היסטוריית הרכב</button>
      <button onClick={() => onArea('הזמנות')}>הזמנות לרכב</button>
      <button onClick={() => onArea('זיהוי אוטומטי')}>חיבור הטלפון וזיהוי אוטומטי</button>
    </div>
    {area && <div role="status"><h4>{area} — {vehicle.display_name}</h4>
      <p>{area === 'זיהוי אוטומטי' ? 'הגדרת זיהוי אוטומטי לטלפון תתווסף בהמשך. אין טלפון שהוגדר דרך מסך זה.'
        : 'המסך הייעודי לרכב יתווסף בהמשך. כרגע ניתן להשתמש במסך המשפחתי דרך לוח הבקרה.'}</p></div>}
  </section>
}

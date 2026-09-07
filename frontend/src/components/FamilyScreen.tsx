import { useEffect, useRef, useState } from 'react'
import {
  getFamily,
  resolveFamilyAddress,
  updateFamilyAddress,
  updateFamilyMemberRole,
  type FamilyProfile,
  type FamilyRole,
} from '../api/apiClient'
import { DashboardCategoryIcon } from './DashboardCategoryIcon'

const ROLE_LABELS: Record<Exclude<FamilyRole, null>, string> = {
  parent: 'הורה',
  child: 'ילד/ילדה',
}

function roleLabel(role: FamilyRole) {
  return role === null ? '' : ROLE_LABELS[role]
}

export function FamilyScreen({ accessToken, open, onBack }: {
  accessToken: string
  open: boolean
  onBack: () => void
}) {
  const backButtonRef = useRef<HTMLButtonElement | null>(null)
  const [family, setFamily] = useState<FamilyProfile | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [error, setError] = useState('')
  const [updatingMember, setUpdatingMember] = useState<string | null>(null)
  const [copyFeedback, setCopyFeedback] = useState('')
  const [editingAddress, setEditingAddress] = useState(false)
  const [addressInput, setAddressInput] = useState('')
  const [resolvedAddress, setResolvedAddress] = useState<{ display: string; token: string } | null>(null)
  const [addressBusy, setAddressBusy] = useState(false)
  const [addressError, setAddressError] = useState('')

  useEffect(() => {
    if (!open) return
    backButtonRef.current?.focus({ preventScroll: true })
    const controller = new AbortController()
    getFamily(accessToken, { signal: controller.signal })
      .then(setFamily)
      .catch((requestError: unknown) => {
        if (requestError instanceof DOMException && requestError.name === 'AbortError') return
        setError('לא הצלחנו לטעון את פרטי המשפחה.')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [accessToken, loadAttempt, open])

  const changeRole = async (memberRef: string, role: FamilyRole) => {
    if (!family?.can_edit_roles || updatingMember) return
    setUpdatingMember(memberRef)
    setError('')
    try {
      const updated = await updateFamilyMemberRole(accessToken, memberRef, role)
      setFamily((current) => current ? {
        ...current,
        members: current.members.map((member) => (
          member.member_ref === updated.member_ref ? updated : member
        )),
      } : current)
    } catch {
      setError('לא הצלחנו לעדכן את התפקיד. נסו שוב.')
    } finally {
      setUpdatingMember(null)
    }
  }

  const copyFamilyCode = async () => {
    if (!family) return
    try {
      await navigator.clipboard.writeText(family.family_code)
      setCopyFeedback('הועתק ✓')
    } catch {
      setCopyFeedback('לא הצלחנו להעתיק')
    }
  }

  const startAddressEdit = () => {
    if (!family?.can_edit_roles) return
    setAddressInput(family.home_address)
    setResolvedAddress(null)
    setAddressError('')
    setEditingAddress(true)
  }

  const checkAddress = async () => {
    if (addressBusy || !addressInput.trim()) return
    setAddressBusy(true)
    setAddressError('')
    try {
      const resolved = await resolveFamilyAddress(accessToken, addressInput.trim())
      setResolvedAddress({ display: resolved.display_address, token: resolved.resolution_token })
    } catch {
      setAddressError('לא הצלחנו לאמת את הכתובת. בדקו את הפרטים ונסו שוב.')
    } finally {
      setAddressBusy(false)
    }
  }

  const confirmAddress = async () => {
    if (addressBusy || !resolvedAddress) return
    setAddressBusy(true)
    setAddressError('')
    try {
      const updated = await updateFamilyAddress(accessToken, resolvedAddress.token)
      setFamily((current) => current ? { ...current, home_address: updated.home_address } : current)
      setEditingAddress(false)
      setResolvedAddress(null)
    } catch {
      setResolvedAddress(null)
      setAddressError('לא הצלחנו לעדכן את הכתובת. הכתובת הקודמת נשארה ללא שינוי.')
    } finally {
      setAddressBusy(false)
    }
  }

  return (
    <section
      className={`category-placeholder-screen family-screen${open ? ' is-open' : ''}`}
      dir="rtl"
      role="dialog"
      aria-modal="true"
      aria-label="משפחה"
      aria-hidden={!open}
      inert={!open}
    >
      <header className="dashboard-header category-placeholder-header">
        <button ref={backButtonRef} type="button" onClick={onBack} aria-label="חזרה ללוח הבקרה">
          <span aria-hidden="true">×</span>
        </button>
        <h1>Family Car Agent</h1>
        <span aria-hidden="true" />
      </header>

      <div className="family-screen-scroll">
        <div className="family-screen-title">
          <DashboardCategoryIcon icon="people" />
          <h2>משפחה</h2>
        </div>

        {loading && !family ? <p className="family-screen-state" role="status">טוענים את המשפחה…</p> : null}
        {error ? (
          <div className="family-screen-error" role="alert">
            <p>{error}</p>
            {!family ? <button type="button" onClick={() => {
              setLoading(true)
              setError('')
              setLoadAttempt((value) => value + 1)
            }}>נסו שוב</button> : null}
          </div>
        ) : null}

        {family ? (
          <div className="family-details">
            <section aria-labelledby="family-members-heading">
              <h3 id="family-members-heading">אנשי המשפחה</h3>
              <div className="family-members">
                {family.members.map((member) => (
                  <article className="family-member" key={member.member_ref}>
                    <span className="family-member-avatar" aria-hidden="true">{member.name.trim().charAt(0)}</span>
                    <div className="family-member-copy">
                      <strong>{member.name}</strong>
                      {member.is_family_admin ? <small>מנהל המשפחה</small> : null}
                      {!family.can_edit_roles && member.role ? <span>{roleLabel(member.role)}</span> : null}
                    </div>
                    {family.can_edit_roles ? (
                      <label className="family-role-field">
                        <span className="visually-hidden">תפקיד עבור {member.name}</span>
                        <select
                          value={member.role ?? ''}
                          disabled={updatingMember === member.member_ref}
                          onChange={(event) => void changeRole(
                            member.member_ref,
                            (event.target.value || null) as FamilyRole,
                          )}
                        >
                          <option value="">ללא תפקיד</option>
                          <option value="parent">הורה</option>
                          <option value="child">ילד/ילדה</option>
                        </select>
                      </label>
                    ) : null}
                  </article>
                ))}
              </div>
            </section>

            <section className="family-info-card family-address-card">
              <h3>כתובת</h3>
              {!editingAddress ? (
                <>
                  <p>{family.home_address}</p>
                  {family.can_edit_roles ? <button type="button" onClick={startAddressEdit}>עריכת כתובת</button> : null}
                </>
              ) : (
                <div className="family-address-editor">
                  <label htmlFor="family-address-input">כתובת חדשה</label>
                  <input
                    id="family-address-input"
                    value={addressInput}
                    disabled={addressBusy}
                    onChange={(event) => {
                      setAddressInput(event.target.value)
                      setResolvedAddress(null)
                      setAddressError('')
                    }}
                    placeholder="עיר, רחוב, מספר בית"
                  />
                  {resolvedAddress ? (
                    <div className="family-address-confirmation" role="status">
                      <span>הכתובת שנמצאה</span>
                      <strong>{resolvedAddress.display}</strong>
                      <button type="button" disabled={addressBusy} onClick={() => void confirmAddress()}>אישור שינוי</button>
                    </div>
                  ) : <button type="button" disabled={addressBusy || !addressInput.trim()} onClick={() => void checkAddress()}>{addressBusy ? 'בודקים…' : 'בדיקת כתובת'}</button>}
                  {addressError ? <p className="family-address-error" role="alert">{addressError}</p> : null}
                  <button type="button" className="family-address-cancel" disabled={addressBusy} onClick={() => { setEditingAddress(false); setResolvedAddress(null); setAddressError('') }}>ביטול</button>
                </div>
              )}
            </section>

            <section className="family-info-card family-code-card">
              <h3>קוד משפחתי</h3>
              <strong dir="ltr">{family.family_code}</strong>
              <button type="button" onClick={() => void copyFamilyCode()}>העתק</button>
              <span role="status" aria-live="polite">{copyFeedback}</span>
            </section>
          </div>
        ) : null}
      </div>
    </section>
  )
}

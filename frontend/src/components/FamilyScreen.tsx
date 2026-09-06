import { useEffect, useRef, useState } from 'react'
import {
  getFamily,
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

            <section className="family-info-card">
              <h3>כתובת</h3>
              <p>{family.home_address}</p>
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

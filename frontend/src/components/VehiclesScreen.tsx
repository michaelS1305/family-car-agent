import { useEffect, useRef } from 'react'
import { DashboardCategoryIcon } from './DashboardCategoryIcon'

export function VehiclesScreen({ open, onBack }: {
  open: boolean
  onBack: () => void
}) {
  const backButtonRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (open) backButtonRef.current?.focus({ preventScroll: true })
  }, [open])

  return (
    <section
      className={`category-placeholder-screen vehicles-screen${open ? ' is-open' : ''}`}
      dir="rtl"
      role="dialog"
      aria-modal="true"
      aria-label="רכבים"
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

      <div className="vehicles-screen-content">
        <div className="family-screen-title vehicles-screen-title">
          <DashboardCategoryIcon icon="car" />
          <h2>רכבים</h2>
        </div>

        <section className="vehicles-development-card" aria-labelledby="vehicles-development-title">
          <DashboardCategoryIcon icon="settings" />
          <h3 id="vehicles-development-title">בפיתוח</h3>
          <p>הפיצ׳ר הזה כרגע עוד נמצא בפיתוח,<br />ויש עוד למה לחכות.</p>
        </section>
      </div>
    </section>
  )
}

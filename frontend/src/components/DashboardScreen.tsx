import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type RefObject,
  type KeyboardEvent,
  type PointerEvent,
} from 'react'
import {
  DASHBOARD_CATEGORIES,
  categoryIndexForRotation,
  categoryPosition,
  confirmDashboardCategory,
  moveRotarySelection,
  normalizeAngleDelta,
  snapRotaryRotation,
  type DashboardCategory,
} from '../dashboard/rotarySelector'

function CategoryIcon({ icon }: { icon: DashboardCategory['icon'] }) {
  const common = {
    width: 30,
    height: 30,
    viewBox: '0 0 32 32',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  }

  if (icon === 'people') {
    return <svg {...common}><circle cx="16" cy="9" r="4" /><circle cx="7" cy="12" r="3" /><circle cx="25" cy="12" r="3" /><path d="M9.5 25v-3.5c0-3.5 2.9-6.3 6.5-6.3s6.5 2.8 6.5 6.3V25M2.5 25v-2.5c0-2.8 2-5 4.7-5M29.5 25v-2.5c0-2.8-2-5-4.7-5" /></svg>
  }
  if (icon === 'car') {
    return <svg {...common}><path d="M5 20v-5l2.7-7h16.6l2.7 7v5" /><path d="M4 16h24v7H4zM8 23v3M24 23v3" /><circle cx="9" cy="19.5" r="1.5" /><circle cx="23" cy="19.5" r="1.5" /></svg>
  }
  if (icon === 'settings') {
    return <svg {...common}><circle cx="16" cy="16" r="4" /><path d="M16 3v3M16 26v3M3 16h3M26 16h3M6.8 6.8l2.1 2.1M23.1 23.1l2.1 2.1M25.2 6.8l-2.1 2.1M8.9 23.1l-2.1 2.1" /><circle cx="16" cy="16" r="10" /></svg>
  }
  if (icon === 'history') {
    return <svg {...common}><path d="M7 7h13l5 5v13H7z" /><path d="M20 7v6h6M11 17h10M11 21h8M11 13h4" /></svg>
  }
  return <svg {...common}><rect x="5" y="7" width="22" height="20" rx="3" /><path d="M10 4v6M22 4v6M5 13h22M10 18h4M18 18h4M10 22h4" /></svg>
}

function RotarySelector({
  confirmButtonRef,
  onConfirm,
}: {
  confirmButtonRef: RefObject<HTMLButtonElement | null>
  onConfirm: (category: DashboardCategory) => void
}) {
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [dragging, setDragging] = useState(false)
  const selectorRef = useRef<HTMLDivElement | null>(null)
  const dialRef = useRef<HTMLDivElement | null>(null)
  const lastPointerAngleRef = useRef(0)
  const rotationRef = useRef(0)
  const draggingRef = useRef(false)
  const snapFrameRef = useRef<number | null>(null)

  useEffect(() => () => {
    if (snapFrameRef.current !== null) window.cancelAnimationFrame(snapFrameRef.current)
  }, [])

  const applyRotation = (nextRotation: number) => {
    rotationRef.current = nextRotation
    selectorRef.current?.style.setProperty('--rotary-angle', `${nextRotation}deg`)
    const nextIndex = categoryIndexForRotation(nextRotation)
    setSelectedIndex((current) => current === nextIndex ? current : nextIndex)
  }

  const pointerAngle = (event: PointerEvent) => {
    const bounds = dialRef.current?.getBoundingClientRect()
    if (!bounds) return 0
    return Math.atan2(
      event.clientY - (bounds.top + (bounds.height / 2)),
      event.clientX - (bounds.left + (bounds.width / 2)),
    ) * (180 / Math.PI)
  }

  const finishRotation = (event: PointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current) return
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    const snapped = snapRotaryRotation(rotationRef.current)
    draggingRef.current = false
    setDragging(false)
    snapFrameRef.current = window.requestAnimationFrame(() => {
      applyRotation(snapped)
      snapFrameRef.current = null
    })
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    let nextRotation: number | null = null
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
      nextRotation = moveRotarySelection(rotationRef.current, 1)
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
      nextRotation = moveRotarySelection(rotationRef.current, -1)
    } else if (event.key === 'Home') {
      nextRotation = 0
    } else if (event.key === 'End') {
      nextRotation = (DASHBOARD_CATEGORIES.length - 1) * (360 / DASHBOARD_CATEGORIES.length)
    }
    if (nextRotation === null) return
    event.preventDefault()
    applyRotation(nextRotation)
  }

  const selectedCategory = DASHBOARD_CATEGORIES[selectedIndex]

  return (
    <div ref={selectorRef} className={`rotary-selector${dragging ? ' is-dragging' : ''}`}>
      <div className="rotary-glass-disc" aria-hidden="true" />
      <div className="rotary-selection-glow" aria-hidden="true" />
      {DASHBOARD_CATEGORIES.map((category, index) => {
        const position = categoryPosition(index, 34)
        const selected = index === selectedIndex
        return (
          <div
            className={`rotary-category${selected ? ' is-selected' : ''}`}
            key={category.id}
            style={{ left: `${position.left}%`, top: `${position.top}%` }}
            aria-hidden="true"
          >
            <CategoryIcon icon={category.icon} />
            <span>{category.label}</span>
          </div>
        )
      })}
      <div
        ref={dialRef}
        className="rotary-touch-surface"
        role="slider"
        tabIndex={0}
        aria-label="בחירת אזור באפליקציה"
        aria-valuemin={1}
        aria-valuemax={DASHBOARD_CATEGORIES.length}
        aria-valuenow={selectedIndex + 1}
        aria-valuetext={selectedCategory.label}
        onKeyDown={handleKeyDown}
        onPointerDown={(event) => {
          if (snapFrameRef.current !== null) window.cancelAnimationFrame(snapFrameRef.current)
          event.currentTarget.setPointerCapture(event.pointerId)
          lastPointerAngleRef.current = pointerAngle(event)
          draggingRef.current = true
          setDragging(true)
        }}
        onPointerMove={(event) => {
          if (!draggingRef.current || !event.currentTarget.hasPointerCapture(event.pointerId)) return
          const nextPointerAngle = pointerAngle(event)
          const delta = normalizeAngleDelta(nextPointerAngle - lastPointerAngleRef.current)
          lastPointerAngleRef.current = nextPointerAngle
          applyRotation(rotationRef.current + delta)
        }}
        onPointerUp={finishRotation}
        onPointerCancel={finishRotation}
      />
      <svg className="rotary-affordance" viewBox="0 0 100 100" aria-hidden="true">
        <path d="M31 65a25 25 0 0 1 0-30" />
        <path d="m27 39 4-4 4 4M69 35a25 25 0 0 1 0 30" />
        <path d="m65 61 4 4 4-4" />
      </svg>
      <button
        ref={confirmButtonRef}
        type="button"
        className="rotary-knob"
        aria-label={`פתיחת ${selectedCategory.label}`}
        onClick={() => onConfirm(confirmDashboardCategory(selectedIndex))}
      >
        <span className="rotary-notch" aria-hidden="true" />
        <strong>OK</strong>
      </button>
    </div>
  )
}

function CategoryPlaceholderScreen({
  category,
  open,
  onBack,
}: {
  category: DashboardCategory
  open: boolean
  onBack: () => void
}) {
  const backButtonRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (open) backButtonRef.current?.focus({ preventScroll: true })
  }, [open])

  return (
    <section
      className={`category-placeholder-screen${open ? ' is-open' : ''}`}
      dir="rtl"
      role="dialog"
      aria-modal="true"
      aria-label={category.label}
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
      <h2>{category.label}</h2>
    </section>
  )
}

export function DashboardScreen({
  open,
  userName,
  version,
  onClose,
  onLogout,
}: {
  open: boolean
  userName: string
  version: string
  onClose: () => void
  onLogout: () => Promise<void>
}) {
  const closeButtonRef = useRef<HTMLButtonElement | null>(null)
  const confirmButtonRef = useRef<HTMLButtonElement | null>(null)
  const categoryOpenFrameRef = useRef<number | null>(null)
  const [activeCategory, setActiveCategory] = useState<DashboardCategory | null>(null)
  const [categoryOpen, setCategoryOpen] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)

  const closeCategory = useCallback(() => {
    if (categoryOpenFrameRef.current !== null) {
      window.cancelAnimationFrame(categoryOpenFrameRef.current)
      categoryOpenFrameRef.current = null
    }
    setCategoryOpen(false)
    window.requestAnimationFrame(() => confirmButtonRef.current?.focus({ preventScroll: true }))
  }, [])

  const openCategory = useCallback((category: DashboardCategory) => {
    if (categoryOpenFrameRef.current !== null) window.cancelAnimationFrame(categoryOpenFrameRef.current)
    setActiveCategory(category)
    setCategoryOpen(false)
    categoryOpenFrameRef.current = window.requestAnimationFrame(() => {
      setCategoryOpen(true)
      categoryOpenFrameRef.current = null
    })
  }, [])

  useEffect(() => () => {
    if (categoryOpenFrameRef.current !== null) window.cancelAnimationFrame(categoryOpenFrameRef.current)
  }, [])

  useEffect(() => {
    if (!open) return
    if (!categoryOpen) closeButtonRef.current?.focus({ preventScroll: true })
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (categoryOpen) closeCategory()
      else onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [categoryOpen, closeCategory, onClose, open])

  const handleLogout = async () => {
    if (loggingOut) return
    setLoggingOut(true)
    try {
      await onLogout()
    } finally {
      setLoggingOut(false)
    }
  }

  return (
    <section
      className={`dashboard-screen${open ? ' is-open' : ''}`}
      dir="rtl"
      role="dialog"
      aria-modal="true"
      aria-label="לוח הבקרה"
      aria-hidden={!open}
      inert={!open}
    >
      <div className="dashboard-content" inert={categoryOpen}>
        <header className="dashboard-header">
          <button ref={closeButtonRef} type="button" onClick={onClose} aria-label="חזרה לצ׳אט">
            <span aria-hidden="true">×</span>
          </button>
          <strong>Family Car Agent</strong>
          <span aria-hidden="true" />
        </header>

        <p className="dashboard-greeting">היי, {userName}</p>
        <p className="dashboard-instruction">סובב את המתג לשירות מבוקש</p>

        <div className="dashboard-selector-area">
          <RotarySelector
            confirmButtonRef={confirmButtonRef}
            onConfirm={openCategory}
          />
        </div>

        <footer className="dashboard-footer">
          <button type="button" className="dashboard-logout" disabled={loggingOut} onClick={() => void handleLogout()}>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 5H5v14h5M14 8l4 4-4 4M8 12h10" /></svg>
            <span>{loggingOut ? 'מתנתקים…' : 'התנתקות'}</span>
          </button>
          <small>v{version}</small>
        </footer>
      </div>

      {activeCategory ? (
        <CategoryPlaceholderScreen category={activeCategory} open={categoryOpen} onBack={closeCategory} />
      ) : null}
    </section>
  )
}

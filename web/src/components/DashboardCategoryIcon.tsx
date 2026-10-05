import type { DashboardCategory } from '../dashboard/rotarySelector'

export function DashboardCategoryIcon({ icon }: { icon: DashboardCategory['icon'] }) {
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

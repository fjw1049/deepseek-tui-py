import { useId } from 'react'
import { pluginVisual } from './plugin-presentation'

/** Shared identity for plugin lists, details, and the built-in computer tool. */
export function PluginIcon({ pluginId }: { pluginId: string }): React.JSX.Element {
  const key = pluginId.trim().toLowerCase()
  const id = useId().replaceAll(':', '')
  const Fallback = pluginVisual(key).icon
  const colors = key === 'data-analysis' ? ['#5EEAD4', '#0D9488']
    : key === 'document-process' || key === 'document-skills' ? ['#C4B5FD', '#7C3AED']
    : key === 'deep-research' ? ['#A5B4FC', '#4F46E5'] : ['#7DD3FC', '#2563EB']
  const ink = `url(#${id}-ink)`
  const paper = `url(#${id}-paper)`
  return <div aria-hidden="true" className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-ds-border bg-ds-card shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
    <svg viewBox="0 0 48 48" className="size-11" fill="none">
      <defs>
        <linearGradient id={`${id}-ink`} x1="6" y1="4" x2="39" y2="44" gradientUnits="userSpaceOnUse">
          <stop stopColor={colors[0]} /><stop offset="1" stopColor={colors[1]} />
        </linearGradient>
        <linearGradient id={`${id}-paper`} x1="10" y1="6" x2="36" y2="39" gradientUnits="userSpaceOnUse">
          <stop stopColor={colors[0]} /><stop offset="1" stopColor={colors[1]} stopOpacity=".8" />
        </linearGradient>
        <filter id={`${id}-depth`} x="-20%" y="-20%" width="140%" height="150%">
          <feDropShadow dx="0" dy="1.2" stdDeviation=".8" floodColor={colors[1]} floodOpacity=".28" />
        </filter>
      </defs>
      <g filter={`url(#${id}-depth)`}>
      {key === 'computer-use' ? <>
        <rect x="3" y="5" width="36" height="32" rx="7" fill={ink} />
        <rect x="5" y="7" width="32" height="28" rx="5" stroke="white" strokeOpacity=".35" />
        <path d="M5 15h32" stroke="#1D4ED8" strokeOpacity=".25" />
        <circle cx="10" cy="11" r="1.3" fill="white" /><circle cx="15" cy="11" r="1.3" fill="white" fillOpacity=".6" />
        <path d="M11 21h11m-11 5h7" stroke="white" strokeOpacity=".65" strokeWidth="2" strokeLinecap="round" />
        <path d="m27 21 15 11-8 2-4 8-5-19a1.5 1.5 0 0 1 2-2Z" fill="#1D4ED8" fillOpacity=".18" transform="translate(0 2)" />
        <path d="m28 20 15 11-8 2-4 8-5-19a1.5 1.5 0 0 1 2-2Z" fill="#EFF6FF" stroke="#2563EB" strokeWidth="1.8" strokeLinejoin="round" />
      </> : key === 'data-analysis' ? <>
        <rect x="5" y="5" width="37" height="37" rx="8" fill={ink} fillOpacity=".23" />
        <path d="M11 14h25M11 23h25M11 32h25" stroke="#0D9488" strokeOpacity=".12" strokeLinecap="round" />
        <rect x="8" y="26" width="9" height="13" rx="2.5" fill={ink} />
        <rect x="20" y="21" width="9" height="18" rx="2.5" fill={ink} />
        <rect x="32" y="15" width="9" height="24" rx="2.5" fill={ink} />
        <path d="m11 21 10-9 8 3 9-8" stroke="#0F766E" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M32 7h6v6" stroke="#0F766E" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="21" cy="12" r="2.4" fill="#CCFBF1" stroke="#0F766E" strokeWidth="1.5" />
      </> : key === 'deep-research' ? <>
        <rect x="5" y="10" width="24" height="31" rx="5" fill={ink} opacity=".8" transform="rotate(-8 17 25)" />
        <rect x="9" y="5" width="25" height="33" rx="5" fill={paper} stroke="#C7D2FE" strokeWidth="1.2" />
        <path d="M15 12h13m-13 5h8m-8 5h6" stroke="white" strokeWidth="2.6" strokeLinecap="round" opacity=".9" />
        <path d="m34 33 8 9" stroke="#4338CA" strokeWidth="6" strokeLinecap="round" />
        <circle cx="29" cy="27" r="11" fill={ink} stroke="#C7D2FE" strokeWidth=".8" />
        <circle cx="29" cy="27" r="7" fill="#EEF2FF" />
        <path d="m25 28 3-3 4 2" stroke="#6366F1" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M25 23a6 6 0 0 1 5-1" stroke="white" strokeWidth="2" strokeLinecap="round" />
      </> : key === 'document-process' || key === 'document-skills' ? <>
        <rect x="5" y="11" width="25" height="32" rx="5" fill={ink} transform="rotate(-7 17 27)" />
        <path d="M15 5h14l8 8v23a4 4 0 0 1-4 4H15a4 4 0 0 1-4-4V9a4 4 0 0 1 4-4Z" fill={paper} stroke="#DDD6FE" strokeWidth="1.2" />
        <path d="M29 5v5a3 3 0 0 0 3 3h5" fill="#EDE9FE" />
        <path d="M17 16h6m-6 6h13m-13 6h8" stroke="white" strokeWidth="2.6" strokeLinecap="round" />
        <path d="m27 33 12-14a2.5 2.5 0 0 1 4 3L31 36l-6 3Z" fill="#7C3AED" stroke="#F5F3FF" strokeWidth="1.3" strokeLinejoin="round" />
        <path d="m37 22 4 3" stroke="#DDD6FE" strokeWidth="2" />
        <path d="m27 33 4 3-6 3Z" fill="#DDD6FE" />
      </> : <Fallback x="8" y="8" width="32" height="32" className="text-ds-muted" strokeWidth={1.8} />}
      </g>
    </svg>
  </div>
}

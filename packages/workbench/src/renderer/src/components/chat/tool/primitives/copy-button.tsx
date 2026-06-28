import { useEffect, useRef, useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '../cn'

const COPY_RESET_MS = 1600

/**
 * Small copy affordance for tool output (stdout / error / diff text). Stays out
 * of the way — faint, hover-revealed via the card's `group` — until the user
 * needs it. Copying command output and stack traces is one of the highest
 * frequency actions in an agent UI, so every expandable tool body offers it.
 */
export function ToolCopyButton({
  text,
  className
}: {
  text: string
  className?: string
}): React.JSX.Element {
  const { t } = useTranslation('common')
  const [copied, setCopied] = useState(false)
  const resetRef = useRef<number | null>(null)

  useEffect(
    () => () => {
      if (resetRef.current !== null) window.clearTimeout(resetRef.current)
    },
    []
  )

  const handleCopy = async (e: React.MouseEvent): Promise<void> => {
    e.stopPropagation()
    try {
      if (!navigator?.clipboard?.writeText) return
      await navigator.clipboard.writeText(text)
      setCopied(true)
      if (resetRef.current !== null) window.clearTimeout(resetRef.current)
      resetRef.current = window.setTimeout(() => setCopied(false), COPY_RESET_MS)
    } catch {
      /* clipboard unavailable — silently ignore */
    }
  }

  const label = copied ? t('copySuccess') : t('copyMessage')

  return (
    <button
      type="button"
      onClick={(e) => void handleCopy(e)}
      title={label}
      aria-label={label}
      className={cn(
        'inline-flex items-center justify-center rounded-md border border-ds-border-muted bg-ds-card/90 p-1 text-ds-faint opacity-0 backdrop-blur-sm transition hover:bg-ds-hover hover:text-ds-ink focus-visible:opacity-100 group-hover:opacity-100',
        copied ? 'text-emerald-500 opacity-100' : '',
        className
      )}
    >
      {copied ? (
        <Check className="h-3.5 w-3.5" strokeWidth={2.1} />
      ) : (
        <Copy className="h-3.5 w-3.5" strokeWidth={1.8} />
      )}
    </button>
  )
}

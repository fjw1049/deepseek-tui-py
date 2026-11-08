import { useState, useSyncExternalStore, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Moon, Sun } from 'lucide-react'
import { THEME_CHANGED_EVENT } from '../../lib/apply-theme'
import { transitionTheme } from '../../lib/theme-transition'

function subscribeTheme(onChange: () => void): () => void {
  window.addEventListener(THEME_CHANGED_EVENT, onChange)
  return () => window.removeEventListener(THEME_CHANGED_EVENT, onChange)
}

function isDarkTheme(): boolean {
  return document.documentElement.getAttribute('data-theme') === 'dark'
}

type Props = {
  className?: string
}

export function ThemeToggle({ className = '' }: Props): ReactElement {
  const { t } = useTranslation('common')
  const dark = useSyncExternalStore(subscribeTheme, isDarkTheme)
  const [saving, setSaving] = useState(false)
  const title = t(dark ? 'themeToggleToLight' : 'themeToggleToDark')
  const Icon = dark ? Sun : Moon

  const onToggle = async (button: HTMLButtonElement): Promise<void> => {
    if (saving) return
    const rect = button.getBoundingClientRect()
    const origin = { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }
    setSaving(true)
    try {
      const next = await window.dsGui.setSettings({ theme: isDarkTheme() ? 'light' : 'dark' })
      await transitionTheme(next.theme, origin)
    } catch {
      // Keep the previous live value; settings write failed.
    } finally {
      setSaving(false)
    }
  }

  return (
    <button
      type="button"
      disabled={saving}
      onClick={(event) => void onToggle(event.currentTarget)}
      title={title}
      aria-label={title}
      className={`ds-no-drag relative inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-ds-ink transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50 ${className}`.trim()}
    >
      <Icon className="h-4 w-4" strokeWidth={1.75} aria-hidden />
    </button>
  )
}

import { useState, useSyncExternalStore, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { LayoutDashboard } from 'lucide-react'
import type { EmptyHomeLayout } from '@shared/appearance'
import { useChatStore } from '../../store/chat-store'
import {
  applyAppearance,
  getEmptyHomeLayout,
  subscribeAppearance
} from '../../lib/apply-appearance'

type Props = {
  className?: string
}

export function EmptyHomeLayoutToggle({ className = '' }: Props): ReactElement | null {
  const { t } = useTranslation('common')
  const layout = useSyncExternalStore(subscribeAppearance, getEmptyHomeLayout)
  const [saving, setSaving] = useState(false)
  const showLayoutToggle = useChatStore((s) =>
    s.route === 'chat' && s.blocks.length === 0 && !s.busy &&
    s.liveAssistant.trim().length === 0 && s.liveReasoning.trim().length === 0
  )
  const simple = layout === 'simple'
  const title = t(simple ? 'emptyHomeLayoutToggleToNormal' : 'emptyHomeLayoutToggleToSimple')

  const onToggle = async (): Promise<void> => {
    if (saving) return
    const value: EmptyHomeLayout = getEmptyHomeLayout() === 'simple' ? 'normal' : 'simple'
    setSaving(true)
    try {
      const next = await window.dsGui.setSettings({ appearance: { emptyHomeLayout: value } })
      applyAppearance(next.appearance)
    } catch {
      // Keep the previous live value; settings write failed.
    } finally {
      setSaving(false)
    }
  }

  if (!showLayoutToggle) return null

  return (
    <button
      type="button"
      disabled={saving}
      onClick={() => void onToggle()}
      title={title}
      aria-label={title}
      aria-pressed={simple}
      className={`ds-no-drag relative inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50 ${className}`.trim()}
    >
      <LayoutDashboard
        className={`h-4 w-4 transition-transform duration-200 ease-out ${simple ? 'rotate-180' : 'rotate-0'}`}
        strokeWidth={1.75}
        aria-hidden
      />
    </button>
  )
}

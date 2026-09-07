import { useCallback, useState, useSyncExternalStore, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Bell, LayoutDashboard } from 'lucide-react'
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

export function EmptyHomeLayoutToggle({ className = '' }: Props): ReactElement {
  const { t } = useTranslation('common')
  const layout = useSyncExternalStore(subscribeAppearance, getEmptyHomeLayout)
  const [saving, setSaving] = useState(false)
  const threads = useChatStore((s) => s.threads)
  const unreadThreadIds = useChatStore((s) => s.unreadThreadIds)
  const watchTurnCompletion = useChatStore((s) => s.watchTurnCompletion)
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const showNotifications = useChatStore((s) =>
    s.route !== 'chat' || s.blocks.length > 0 || s.busy ||
    s.liveAssistant.trim().length > 0 || s.liveReasoning.trim().length > 0
  )
  const setRoute = useChatStore((s) => s.setRoute)
  const runtimeConnection = useChatStore((s) => s.runtimeConnection)
  const selectThread = useChatStore((s) => s.selectThread)
  const unreadThreads = threads.filter((thread) =>
    unreadThreadIds[thread.id] === true && thread.id !== activeThreadId &&
    !thread.archived && !watchTurnCompletion[thread.id] &&
    thread.status?.trim().toLowerCase() !== 'running'
  )
  const nextUnread = unreadThreads[0]

  const simple = layout === 'simple'
  const title = showNotifications
    ? nextUnread
      ? t('openNextUnreadThread', { count: unreadThreads.length, title: nextUnread.title })
      : t('noUnreadThreads')
    : simple
      ? t('emptyHomeLayoutToggleToNormal')
      : t('emptyHomeLayoutToggleToSimple')

  const onToggle = useCallback(async () => {
    if (saving) return
    if (showNotifications) {
      if (!nextUnread) return
      setSaving(true)
      try {
        setRoute('chat')
        await selectThread(nextUnread.id)
      } finally {
        setSaving(false)
      }
      return
    }
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
  }, [saving, showNotifications, nextUnread, selectThread, setRoute])

  return (
    <button
      type="button"
      disabled={saving || (showNotifications && Boolean(nextUnread) && runtimeConnection !== 'ready')}
      onClick={() => void onToggle()}
      title={title}
      aria-label={title}
      aria-pressed={showNotifications ? undefined : simple}
      className={`ds-no-drag relative inline-flex h-9 w-9 shrink-0 items-center justify-center ${showNotifications ? 'rounded-full text-ds-ink' : 'rounded-xl text-ds-faint'} transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50 ${className}`.trim()}
    >
      {showNotifications ? <Bell className="h-4 w-4" strokeWidth={1.75} aria-hidden /> : <LayoutDashboard
        className={`h-4 w-4 transition-transform duration-200 ease-out ${
          simple ? 'rotate-180' : 'rotate-0'
        }`}
        strokeWidth={1.75}
        aria-hidden
      />}
      {showNotifications && nextUnread ? (
        <span aria-hidden="true" className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-orange-500" />
      ) : null}
    </button>
  )
}

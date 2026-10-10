import { useEffect, useRef, useState } from 'react'
import { Hand } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useChatStore } from '../store/chat-store'
import { BROWSER_ACTIVITY_EVENT } from '../lib/browser-activity'
import { formatAutomationApiError } from '../lib/automation-runtime-client'
import './browser-assistance.css'

import { type Assistance } from './BrowserAssistanceCard'
import { useBrowserAssistanceStore } from '../store/browser-assistance-store'
export const ASSISTANCE_CHANGED = 'workbench:browser-assistance-changed'
export async function respondToAssistance(threadId: string, id: string, choice: string, text = ''): Promise<void> {
  const result = await window.dsGui.runtimeRequest(`/v1/threads/${encodeURIComponent(threadId)}/browser/assistance`, 'POST', JSON.stringify({ request_id: id, choice, text }))
  if (!result.ok) throw new Error(formatAutomationApiError(result.body, `HTTP ${result.status}`))
  useBrowserAssistanceStore.setState(state => ({
    revision: state.revision + 1,
    items: choice === 'takeover' ? state.items.map(item => item.id === id && item.thread_id === threadId ? { ...item, status: 'human' } : item)
      : state.items.filter(item => item.id !== id || item.thread_id !== threadId)
  }))
  window.dispatchEvent(new Event(ASSISTANCE_CHANGED))
}

/** Lives outside browser visibility so collapsed panels and background chats still notify. */
export function BrowserAssistance({ visible, enabled }: { visible: boolean; enabled: boolean }): React.ReactElement | null {
  const { t } = useTranslation('common')
  const activeId = useChatStore(s => s.activeThreadId)
  const items = useBrowserAssistanceStore(s => s.items)
  const [openThreadId, setOpenThreadId] = useState<string | null>(null)
  const notified = useRef(new Set<string>())
  const [revision, setRevision] = useState(0)
  const reveal = (threadId: string): void => { window.dispatchEvent(new CustomEvent(BROWSER_ACTIVITY_EVENT, { detail: { threadId } })) }
  useEffect(() => {
    const changed = (): void => setRevision(n => n + 1)
    window.addEventListener(ASSISTANCE_CHANGED, changed)
    return () => window.removeEventListener(ASSISTANCE_CHANGED, changed)
  }, [])
  const openThread = (threadId: string): void => {
    setOpenThreadId(threadId)
    void useChatStore.getState().selectThread(threadId).catch(() => setOpenThreadId(null))
  }
  useEffect(() => window.dsGui.onAssistanceNotificationClick?.(openThread), [])
  useEffect(() => {
    if (!openThreadId || activeId !== openThreadId) return
    const frame = requestAnimationFrame(() => { reveal(openThreadId); setOpenThreadId(null) })
    return () => cancelAnimationFrame(frame)
  }, [activeId, openThreadId])
  useEffect(() => {
    if (!enabled) { useBrowserAssistanceStore.setState({ items: [], connectionError: '' }); return }
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    async function poll(): Promise<void> {
      const requestRevision = useBrowserAssistanceStore.getState().revision
      try {
        const response = await window.dsGui.runtimeRequest('/v1/browser-assistance', 'GET')
        if (!response.ok) throw new Error(formatAutomationApiError(response.body, `HTTP ${response.status}`))
        const next = (JSON.parse(response.body) as { items: Assistance[] }).items
        if (disposed || requestRevision !== useBrowserAssistanceStore.getState().revision) return
        useBrowserAssistanceStore.setState({ items: next, connectionError: '' })
        for (const item of next) {
          if (notified.current.has(item.id)) continue
          notified.current.add(item.id)
          void window.dsGui.showTurnCompleteNotification({ kind: 'browser-assistance', threadId: item.thread_id, title: t('browserAssistTitle'), body: t('browserAssistNotification') }).catch(() => {})
        }
        const ids = new Set(next.map(item => item.id))
        for (const id of notified.current) if (!ids.has(id)) notified.current.delete(id)
      } catch (e) { if (!disposed) useBrowserAssistanceStore.setState({ connectionError: e instanceof Error ? e.message : String(e) }) }
      finally { if (!disposed) timer = setTimeout(() => void poll(), 1500) }
    }
    void poll()
    return () => { disposed = true; clearTimeout(timer) }
  }, [enabled, revision, t])
  const waiting = items.filter(item => !visible || item.thread_id !== activeId)
  const other = waiting[0]
  return other ? <div className="ds-assistance-background" role="status"><Hand size={15} /><span>{t('browserAssistBackground', { count: waiting.length })}</span><button onClick={() => openThread(other.thread_id)}>{t('browserAssistView')}</button></div> : null
}

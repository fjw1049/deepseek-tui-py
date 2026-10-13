import { useEffect, useState, type ReactElement } from 'react'
import { ArrowRightToLine, FolderClosed, GitBranch, ChevronDown, ChevronRight, Circle, CircleAlert, CircleCheck, CirclePause, Loader2, MessageCircleQuestion } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { activityDismissalKey, type ActivityRow } from '../../lib/sidebar-activity'
import { isChatsWorkspace, normalizeWorkspaceRoot } from '../../lib/workspace-path'
import { workspaceLabelFromPath } from '../../lib/workspace-label'
import './sidebar-activity.css'
import { HoverMarqueeText } from '../HoverMarqueeText'
import { ActivitySwipeRow } from './ActivitySwipeRow'

const statusIcons = { waiting: MessageCircleQuestion, failed: CircleAlert, running: Loader2, unread: CircleCheck, completed: CircleCheck, idle: Circle, stopped: CirclePause }

const branchPath = (thread: ActivityRow['thread']): string => {
  const path = normalizeWorkspaceRoot(thread.worktreePath || thread.workspace)
  return isChatsWorkspace(path) ? '' : path
}

export function SidebarActivity({ rows, activeThreadId, runtimeReady, onSelectThread, onDismiss, onRevealThread }: {
  onRevealThread: (id: string) => void
  rows: ActivityRow[]
  activeThreadId: string | null
  runtimeReady: boolean
  onSelectThread: (id: string) => void
  onDismiss: (row: ActivityRow) => void
}): ReactElement {
  const { t } = useTranslation('common')
  const [collapsed, setCollapsed] = useState(false)
  const [openId, setOpenId] = useState<string | null>(null)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [branches, setBranches] = useState<Record<string, string | null>>({})
  const pathsKey = [...new Set(rows.map(({ thread }) => branchPath(thread)).filter(Boolean))].sort().join('\0')
  useEffect(() => {
    if (!pathsKey || typeof window.dsGui?.getGitBranches !== 'function') {
      setBranches({})
      return
    }
    let cancelled = false
    void Promise.all(pathsKey.split('\0').map(async (path): Promise<[string, string | null]> => {
      try {
        const result = await window.dsGui.getGitBranches(path)
        return [path, result.ok ? result.currentBranch : null]
      } catch {
        return [path, null]
      }
    })).then((entries) => { if (!cancelled) setBranches(Object.fromEntries(entries)) })
    return () => { cancelled = true }
  }, [pathsKey])
  const total = rows.length
  return (
    <section id="sidebar-activity" className="ds-activity ds-no-drag min-h-0 flex-1" aria-label={t('activityTitle')}>
      <div className="ds-sidebar-section-heading shrink-0">
        <div className="ds-sidebar-projects-toolbar ds-sidebar-projects-toolbar--fixed ds-no-drag shrink-0">
          <button type="button" className="flex h-7 min-w-0 flex-1 items-center gap-1.5 text-left"
            aria-expanded={!collapsed} aria-controls="sidebar-activity-list"
            onClick={() => setCollapsed(!collapsed)}>
            {collapsed
              ? <ChevronRight className="h-3 w-3 shrink-0 text-ds-faint" strokeWidth={2} />
              : <ChevronDown className="h-3 w-3 shrink-0 text-ds-faint" strokeWidth={2} />}
            <span className="ds-sidebar-section-label min-w-0 truncate">{t('activityTitle')}</span>
          </button>
          <span className="ds-activity-total flex h-7 w-7 shrink-0 items-center justify-center">{total}</span>
        </div>
      </div>
      {!runtimeReady && <p className="ds-activity-offline" role="status">{t('activityOffline')}</p>}
      <div id="sidebar-activity-list" className="ds-activity-scroll" hidden={collapsed}>
        {total === 0 ? <div className="ds-activity-empty">
          <CircleCheck size={25} strokeWidth={1.35} />
          <strong>{t('activityEmpty')}</strong><p>{t('activityEmptyHint')}</p>
        </div> : rows.map((activity) => {
          const { thread, status, unread } = activity
          const Icon = statusIcons[status]
          const branch = branches[branchPath(thread)]
          const project = !thread.workspace || isChatsWorkspace(thread.workspace) ? t('sidebarChatBadge') : workspaceLabelFromPath(thread.workspace)
          return <div key={`${thread.id}:${activityDismissalKey(activity)}`} className="ds-activity-item"
            onMouseEnter={() => setHoveredId(thread.id)} onMouseLeave={() => setHoveredId(null)}
            onFocusCapture={() => setHoveredId(thread.id)}
            onBlurCapture={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setHoveredId(null) }}>
            <ActivitySwipeRow
              selected={thread.id === activeThreadId}
              open={openId === thread.id}
              onOpenChange={(open) => setOpenId(open ? thread.id : null)}
              title={`${thread.title} · ${project} · ${t(`activityStatus_${status}`)}`}
              onSelect={() => onSelectThread(thread.id)}
              onDismiss={() => { setOpenId(null); onDismiss(activity) }}
              actions={<div className="ds-activity-actions">
                <button type="button" disabled={!runtimeReady}
                  title={t('activityRevealThread')} aria-label={t('activityRevealThread')}
                  onClick={() => onRevealThread(thread.id)}><ArrowRightToLine size={15} strokeWidth={1.8} /></button>
              </div>}>
              <Icon size={15} strokeWidth={1.8} className={`ds-activity-icon ds-activity-icon--${status} ${status === 'running' ? 'animate-spin motion-reduce:animate-none' : ''}`} />
              <span className="ds-activity-copy"><HoverMarqueeText className="ds-activity-title"
                active={hoveredId === thread.id && openId !== thread.id}
                text={thread.title || thread.id.slice(0, 8)} title={thread.title} />
                <span className="ds-activity-meta">
                  <span className="ds-activity-meta-item" title={thread.workspace}>
                    <FolderClosed size={12} strokeWidth={1.75} aria-hidden="true" /><span>{project}</span>
                  </span>
                  {branch && <><span aria-hidden="true">·</span><span className="ds-activity-meta-item" title={branch}>
                    <GitBranch size={12} strokeWidth={1.75} aria-hidden="true" /><span>{branch}</span>
                  </span></>}
                  {!['completed', 'idle', 'unread'].includes(status) && <><span aria-hidden="true">·</span><span className="ds-activity-meta-item ds-activity-meta-status">
                    <Icon size={12} strokeWidth={1.75} aria-hidden="true" /><span>{t(`activityStatus_${status}`)}</span>
                  </span></>}
                </span>
              </span>
              {unread && <span className="ds-activity-unread" aria-label={t('activityUnreadBadge')} />}
            </ActivitySwipeRow>
          </div>
        })}
      </div>
    </section>
  )
}

import { useState, type ReactElement } from 'react'
import { ChevronDown, ChevronRight, CircleAlert, CircleCheck, Loader2, MessageCircleQuestion } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { ActivityGroup, ActivityGroups } from '../../lib/sidebar-activity'
import { isChatsWorkspace } from '../../lib/workspace-path'
import { workspaceLabelFromPath } from '../../lib/workspace-label'
import './sidebar-activity.css'

const groupOrder: ActivityGroup[] = ['attention', 'running', 'unread']
const statusIcons = { waiting: MessageCircleQuestion, failed: CircleAlert, running: Loader2, unread: CircleCheck }

export function SidebarActivity({ groups, activeThreadId, runtimeReady, onSelectThread }: {
  groups: ActivityGroups
  activeThreadId: string | null
  runtimeReady: boolean
  onSelectThread: (id: string) => void
}): ReactElement {
  const { t } = useTranslation('common')
  const [collapsed, setCollapsed] = useState(false)
  const total = groupOrder.reduce((count, group) => count + groups[group].length, 0)
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
        </div> : groupOrder.map((group) => groups[group].length > 0 && (
          <section key={group} className="ds-activity-group" aria-label={t(`activityGroup_${group}`)}>
            <h3>{t(`activityGroup_${group}`)}<span>{groups[group].length}</span></h3>
            {groups[group].map(({ thread, status, unread }) => {
              const Icon = statusIcons[status]
              const project = !thread.workspace || isChatsWorkspace(thread.workspace) ? t('sidebarChatBadge') : workspaceLabelFromPath(thread.workspace)
              return <button key={thread.id} type="button"
                className={`ds-activity-row ${thread.id === activeThreadId ? 'ds-activity-row--selected' : ''}`}
                aria-current={thread.id === activeThreadId ? 'page' : undefined}
                title={`${thread.title} · ${project} · ${t(`activityStatus_${status}`)}`}
                onClick={() => onSelectThread(thread.id)}>
                <Icon size={15} strokeWidth={1.8} className={`ds-activity-icon ds-activity-icon--${status} ${status === 'running' ? 'animate-spin motion-reduce:animate-none' : ''}`} />
                <span className="ds-activity-copy"><span className="ds-activity-title">{thread.title || thread.id.slice(0, 8)}</span>
                  <span className="ds-activity-meta"><span>{project}</span><span>·</span><span>{t(`activityStatus_${status}`)}</span></span>
                </span>
                {unread && <span className="ds-activity-unread" aria-label={t('activityUnreadBadge')} />}
              </button>
            })}
          </section>
        ))}
      </div>
    </section>
  )
}

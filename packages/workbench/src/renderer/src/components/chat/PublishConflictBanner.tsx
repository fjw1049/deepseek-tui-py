import { useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { useChatStore } from '../../store/chat-store'

/** File-level publish conflicts. Isolation stays off-screen. */
export function PublishConflictBanner(): ReactElement | null {
  const { t } = useTranslation('common')
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const busy = useChatStore((s) => s.busy)
  const resolvePublishConflicts = useChatStore((s) => s.resolvePublishConflicts)
  const thread = useChatStore((s) =>
    s.activeThreadId ? s.threads.find((item) => item.id === s.activeThreadId) ?? null : null
  )
  const [pending, setPending] = useState(false)
  const conflicts = thread?.publishConflicts ?? []
  if (!activeThreadId || !thread?.publishBlocked || conflicts.length === 0) return null

  const run = async (action: 'use_agent' | 'keep_project'): Promise<void> => {
    if (pending || busy) return
    setPending(true)
    try {
      await resolvePublishConflicts(action)
    } finally {
      setPending(false)
    }
  }

  return (
    <div
      className="ds-publish-conflict-banner mx-2 mb-2 rounded-xl border border-ds-border-muted bg-ds-main/40 px-3 py-2.5 sm:mx-3"
      data-publish-conflict-banner="true"
    >
      <p className="text-[13px] font-medium leading-5 text-ds-ink">
        {t('publishConflictTitle', { count: conflicts.length })}
      </p>
      <p className="mt-0.5 text-[12px] leading-5 text-ds-muted">{t('publishConflictBody')}</p>
      <ul className="mt-2 max-h-28 overflow-y-auto font-mono text-[12px] leading-5 text-ds-ink">
        {conflicts.slice(0, 8).map((file) => (
          <li key={file} className="truncate" title={file}>
            {file}
          </li>
        ))}
      </ul>
      <div className="mt-2 flex flex-wrap justify-end gap-2">
        <button
          type="button"
          disabled={pending || busy}
          onClick={() => void run('keep_project')}
          className="rounded-md px-2.5 py-1 text-[12px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50"
        >
          {t('publishConflictKeepProject')}
        </button>
        <button
          type="button"
          disabled={pending || busy}
          onClick={() => void run('use_agent')}
          className="rounded-md bg-accent px-2.5 py-1 text-[12px] font-medium text-white transition hover:brightness-110 disabled:opacity-50"
        >
          {t('publishConflictUseAgent')}
        </button>
      </div>
    </div>
  )
}

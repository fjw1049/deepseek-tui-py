import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement,
  type ReactNode
} from 'react'
import { useTranslation } from 'react-i18next'
import {
  ArchiveRestore,
  Check,
  ChevronDown,
  Folder,
  ListFilter,
  Loader2,
  MoreHorizontal,
  Search,
  Trash2
} from 'lucide-react'
import type { NormalizedThread } from '../../agent/types'
import { getProvider } from '../../agent/registry'
import { useLightDismiss } from '../../hooks/use-light-dismiss'
import { workspaceLabelFromPath } from '../../lib/workspace-label'
import { isChatsWorkspace, normalizeWorkspaceRoot } from '../../lib/workspace-path'
import { useChatStore } from '../../store/chat-store'

type ProjectGroup = {
  key: string
  label: string
  threads: NormalizedThread[]
}

type FilterOption = {
  value: string
  label: string
}

function projectKeyForThread(thread: NormalizedThread): string {
  if (isChatsWorkspace(thread.workspace)) return '__chats__'
  const path = normalizeWorkspaceRoot(thread.workspace)
  return path || '__chats__'
}

function projectLabelForThread(thread: NormalizedThread, chatsLabel: string): string {
  if (isChatsWorkspace(thread.workspace)) return chatsLabel
  const path = normalizeWorkspaceRoot(thread.workspace)
  return path ? workspaceLabelFromPath(path) : chatsLabel
}

/** Match reference screenshot: "2026年6月18日, 17:21" */
function formatArchivedAt(iso: string, locale: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  if (locale.toLowerCase().startsWith('zh')) {
    const hh = String(date.getHours()).padStart(2, '0')
    const mm = String(date.getMinutes()).padStart(2, '0')
    return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日, ${hh}:${mm}`
  }
  try {
    return new Intl.DateTimeFormat(locale, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    }).format(date)
  } catch {
    return iso
  }
}

function ArchiveFilterMenu({
  icon,
  value,
  options,
  onChange,
  ariaLabel
}: {
  icon: ReactNode
  value: string
  options: FilterOption[]
  onChange: (value: string) => void
  ariaLabel: string
}): ReactElement {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const selected = options.find((option) => option.value === value) ?? options[0]

  useLightDismiss({
    open,
    onDismiss: () => setOpen(false),
    refs: [rootRef]
  })

  return (
    <div className="ds-archive-filter" ref={rootRef}>
      <button
        type="button"
        className={`ds-archive-filter__trigger${open ? ' is-open' : ''}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        onClick={() => setOpen((prev) => !prev)}
      >
        <span className="ds-archive-filter__icon">{icon}</span>
        <span className="ds-archive-filter__label">{selected?.label ?? ''}</span>
        <ChevronDown className="ds-archive-filter__chevron" strokeWidth={1.75} />
      </button>
      {open ? (
        <div className="ds-archive-filter__menu" role="listbox" aria-label={ariaLabel}>
          {options.map((option) => {
            const active = option.value === value
            return (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={active}
                className={`ds-archive-filter__option${active ? ' is-active' : ''}`}
                onClick={() => {
                  onChange(option.value)
                  setOpen(false)
                }}
              >
                <span className="ds-archive-filter__option-label">{option.label}</span>
                {active ? <Check className="h-3.5 w-3.5 shrink-0" strokeWidth={2} /> : null}
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}

export function ArchiveSettingsPanel(): ReactElement {
  const { t, i18n } = useTranslation('settings')
  const { t: tCommon } = useTranslation('common')
  const providerId = useChatStore((s) => s.providerId)
  const runtimeConnection = useChatStore((s) => s.runtimeConnection)
  const refreshThreads = useChatStore((s) => s.refreshThreads)

  const [threads, setThreads] = useState<NormalizedThread[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [modeFilter, setModeFilter] = useState('all')
  const [projectFilter, setProjectFilter] = useState('all')
  const [busyIds, setBusyIds] = useState<Record<string, boolean>>({})
  const [batchBusy, setBatchBusy] = useState(false)

  const refresh = useCallback(async (): Promise<void> => {
    setLoading(true)
    setLoadError(null)
    try {
      if (runtimeConnection !== 'ready') {
        setThreads([])
        setLoadError(t('archiveNeedRuntime'))
        return
      }
      const provider = getProvider(providerId)
      const rows = await provider.listThreads({ includeArchived: true })
      setThreads(rows.filter((thread) => thread.archived === true))
    } catch {
      setThreads([])
      setLoadError(t('archiveLoadFailed'))
    } finally {
      setLoading(false)
    }
  }, [providerId, runtimeConnection, t])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const chatsLabel = tCommon('sidebarChatBadge')

  const projectOptions = useMemo((): FilterOption[] => {
    const map = new Map<string, string>()
    for (const thread of threads) {
      const key = projectKeyForThread(thread)
      if (!map.has(key)) map.set(key, projectLabelForThread(thread, chatsLabel))
    }
    return [
      { value: 'all', label: t('archiveFilterAllProjects') },
      ...[...map.entries()]
        .map(([value, label]) => ({ value, label }))
        .sort((a, b) => a.label.localeCompare(b.label, i18n.language))
    ]
  }, [chatsLabel, i18n.language, t, threads])

  const modeOptions = useMemo((): FilterOption[] => {
    const modes = new Set<string>()
    for (const thread of threads) {
      const mode = thread.mode?.trim()
      if (mode) modes.add(mode)
    }
    return [
      { value: 'all', label: t('archiveFilterAllModes') },
      ...[...modes]
        .sort((a, b) => a.localeCompare(b, i18n.language))
        .map((mode) => ({ value: mode, label: mode }))
    ]
  }, [i18n.language, t, threads])

  // Drop stale filter values when the option set shrinks after deletes.
  useEffect(() => {
    if (!modeOptions.some((option) => option.value === modeFilter)) {
      setModeFilter('all')
    }
  }, [modeFilter, modeOptions])

  useEffect(() => {
    if (!projectOptions.some((option) => option.value === projectFilter)) {
      setProjectFilter('all')
    }
  }, [projectFilter, projectOptions])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return threads.filter((thread) => {
      if (modeFilter !== 'all' && thread.mode !== modeFilter) return false
      if (projectFilter !== 'all' && projectKeyForThread(thread) !== projectFilter) return false
      if (!q) return true
      return thread.title.toLowerCase().includes(q)
    })
  }, [modeFilter, projectFilter, query, threads])

  const groups = useMemo((): ProjectGroup[] => {
    const map = new Map<string, ProjectGroup>()
    for (const thread of filtered) {
      const key = projectKeyForThread(thread)
      const existing = map.get(key)
      if (existing) {
        existing.threads.push(thread)
        continue
      }
      map.set(key, {
        key,
        label: projectLabelForThread(thread, chatsLabel),
        threads: [thread]
      })
    }
    return [...map.values()].sort((a, b) => a.label.localeCompare(b.label, i18n.language))
  }, [chatsLabel, filtered, i18n.language])

  const runOnThread = async (threadId: string, action: () => Promise<void>): Promise<void> => {
    setBusyIds((prev) => ({ ...prev, [threadId]: true }))
    setLoadError(null)
    try {
      await action()
      setThreads((prev) => prev.filter((thread) => thread.id !== threadId))
      await refreshThreads()
    } catch (error) {
      const message =
        error instanceof Error && error.message.trim() ? error.message : t('archiveActionFailed')
      setLoadError(message)
    } finally {
      setBusyIds((prev) => {
        const next = { ...prev }
        delete next[threadId]
        return next
      })
    }
  }

  const handleUnarchive = (thread: NormalizedThread): void => {
    const provider = getProvider(providerId)
    if (typeof provider.setThreadArchived !== 'function') {
      setLoadError(t('archiveActionFailed'))
      return
    }
    void runOnThread(thread.id, () => provider.setThreadArchived!(thread.id, false))
  }

  const handleDeleteOne = (thread: NormalizedThread): void => {
    const ok = window.confirm(t('archiveDeleteOneConfirm', { title: thread.title }))
    if (!ok) return
    const provider = getProvider(providerId)
    if (typeof provider.purgeThread !== 'function') {
      setLoadError(t('archiveActionFailed'))
      return
    }
    void runOnThread(thread.id, () => provider.purgeThread!(thread.id))
  }

  const handleDeleteGroup = (group: ProjectGroup): void => {
    if (group.threads.length === 0 || batchBusy) return
    const ok = window.confirm(t('archiveDeleteAllConfirm', { count: group.threads.length }))
    if (!ok) return
    const provider = getProvider(providerId)
    if (typeof provider.purgeThread !== 'function') {
      setLoadError(t('archiveActionFailed'))
      return
    }
    setBatchBusy(true)
    setLoadError(null)
    void (async () => {
      try {
        for (const thread of group.threads) {
          await provider.purgeThread!(thread.id)
        }
        const removed = new Set(group.threads.map((thread) => thread.id))
        setThreads((prev) => prev.filter((thread) => !removed.has(thread.id)))
        await refreshThreads()
      } catch (error) {
        const message =
          error instanceof Error && error.message.trim() ? error.message : t('archiveActionFailed')
        setLoadError(message)
        await refresh()
      } finally {
        setBatchBusy(false)
      }
    })()
  }

  const handleDeleteAll = (): void => {
    if (threads.length === 0 || batchBusy) return
    const ok = window.confirm(t('archiveDeleteAllConfirm', { count: threads.length }))
    if (!ok) return
    const provider = getProvider(providerId)
    setBatchBusy(true)
    setLoadError(null)
    void (async () => {
      try {
        if (typeof provider.purgeArchivedThreads === 'function') {
          await provider.purgeArchivedThreads()
        } else if (typeof provider.purgeThread === 'function') {
          for (const thread of threads) {
            await provider.purgeThread(thread.id)
          }
        } else {
          throw new Error(t('archiveActionFailed'))
        }
        setThreads([])
        await refreshThreads()
      } catch (error) {
        const message =
          error instanceof Error && error.message.trim() ? error.message : t('archiveActionFailed')
        setLoadError(message)
        await refresh()
      } finally {
        setBatchBusy(false)
      }
    })()
  }

  return (
    <div className="ds-archive-panel">
      <div className="ds-archive-panel__toolbar">
        <label className="ds-archive-panel__search">
          <Search className="ds-archive-panel__search-icon" strokeWidth={1.75} />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('archiveSearchPlaceholder')}
          />
        </label>
        <ArchiveFilterMenu
          icon={<ListFilter className="h-3.5 w-3.5" strokeWidth={1.75} />}
          value={modeFilter}
          options={modeOptions}
          onChange={setModeFilter}
          ariaLabel={t('archiveFilterAllModes')}
        />
        <ArchiveFilterMenu
          icon={<Folder className="h-3.5 w-3.5" strokeWidth={1.75} />}
          value={projectFilter}
          options={projectOptions}
          onChange={setProjectFilter}
          ariaLabel={t('archiveFilterAllProjects')}
        />
        <button
          type="button"
          disabled={batchBusy || threads.length === 0 || loading}
          onClick={handleDeleteAll}
          className="ds-archive-panel__delete-all"
        >
          {batchBusy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.75} />
          ) : (
            <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />
          )}
          {t('archiveDeleteAll')}
        </button>
      </div>

      {loadError ? <div className="ds-archive-panel__error">{loadError}</div> : null}

      <div className="ds-archive-panel__body">
        {loading ? (
          <div className="ds-archive-panel__status">
            <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.75} />
            {t('archiveLoading')}
          </div>
        ) : groups.length === 0 ? (
          <div className="ds-archive-panel__empty">
            <p className="ds-archive-panel__empty-title">{t('archiveEmptyTitle')}</p>
            <p className="ds-archive-panel__empty-body">{t('archiveEmptyBody')}</p>
          </div>
        ) : (
          <div className="ds-archive-panel__groups">
            {groups.map((group) => (
              <section key={group.key} className="ds-archive-panel__group">
                <div className="ds-archive-panel__group-head">
                  <Folder className="h-4 w-4 shrink-0 opacity-45" strokeWidth={1.75} />
                  <div className="ds-archive-panel__group-name">{group.label}</div>
                  <div className="ds-archive-panel__group-count">
                    {t('archiveGroupCount', { count: group.threads.length })}
                  </div>
                  <button
                    type="button"
                    disabled={batchBusy}
                    onClick={() => handleDeleteGroup(group)}
                    className="ds-archive-panel__more"
                    title={t('archiveDeleteAll')}
                    aria-label={t('archiveDeleteAll')}
                  >
                    <MoreHorizontal className="h-4 w-4" strokeWidth={1.75} />
                  </button>
                </div>

                <div className="ds-archive-panel__list">
                  {group.threads.map((thread) => {
                    const busy = busyIds[thread.id] === true || batchBusy
                    return (
                      <article key={thread.id} className="ds-archive-row group">
                        <div className="ds-archive-row__content">
                          <h3 className="ds-archive-row__title">
                            {thread.title || t('archiveUntitled')}
                          </h3>
                          <time className="ds-archive-row__time" dateTime={thread.updatedAt}>
                            {formatArchivedAt(thread.updatedAt, i18n.language)}
                          </time>
                        </div>
                        <div className="ds-archive-row__actions">
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => handleDeleteOne(thread)}
                            className="ds-archive-row__icon-btn"
                            title={t('archiveDeleteOne')}
                            aria-label={t('archiveDeleteOne')}
                          >
                            <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => handleUnarchive(thread)}
                            className="ds-archive-row__text-btn"
                            title={t('archiveUnarchive')}
                          >
                            {busyIds[thread.id] === true ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.75} />
                            ) : (
                              <ArchiveRestore className="h-3.5 w-3.5" strokeWidth={1.75} />
                            )}
                            {t('archiveUnarchive')}
                          </button>
                        </div>
                      </article>
                    )
                  })}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

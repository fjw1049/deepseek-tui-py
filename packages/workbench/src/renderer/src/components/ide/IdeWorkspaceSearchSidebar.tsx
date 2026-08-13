import { useEffect, useRef, useState, type ReactElement } from 'react'
import { File, Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { WorkspaceTreeEntry } from '@shared/workspace-file'
import { splitFileNameAndParent } from '../../lib/editor-breadcrumb'
import { EditorListSkeleton } from '../workspace-editor/EditorListSkeleton'

type Props = {
  workspaceRoot: string
  query: string
  onQueryChange: (query: string) => void
  selectedPath: string | null
  onSelectFile: (path: string) => void
}

export function IdeWorkspaceSearchSidebar({
  workspaceRoot,
  query,
  onQueryChange,
  selectedPath,
  onSelectFile
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const [entries, setEntries] = useState<WorkspaceTreeEntry[]>([])
  const [resultQuery, setResultQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [truncated, setTruncated] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestIdRef = useRef(0)

  useEffect(() => {
    const root = workspaceRoot.trim()
    const trimmedQuery = query.trim()
    if (!root || !trimmedQuery) {
      setEntries([])
      setResultQuery('')
      setTruncated(false)
      setError(null)
      setLoading(false)
      return
    }
    if (typeof window.dsGui?.searchWorkspaceEntries !== 'function') {
      setEntries([])
      setError(t('ideWorkspaceSearchUnavailable'))
      setLoading(false)
      return
    }

    const requestId = ++requestIdRef.current
    setLoading(true)
    const timer = window.setTimeout(() => {
      void window.dsGui
        .searchWorkspaceEntries(root, trimmedQuery, 80)
        .then((result) => {
          if (requestId !== requestIdRef.current) return
          if (!result.ok) {
            setEntries([])
            setResultQuery(trimmedQuery)
            setTruncated(false)
            setError(result.message)
            return
          }
          setEntries(result.entries)
          setResultQuery(trimmedQuery)
          setTruncated(result.truncated)
          setError(null)
        })
        .catch((err: unknown) => {
          if (requestId !== requestIdRef.current) return
          setEntries([])
          setResultQuery(trimmedQuery)
          setTruncated(false)
          setError(err instanceof Error ? err.message : String(err))
        })
        .finally(() => {
          if (requestId === requestIdRef.current) setLoading(false)
        })
    }, 160)

    return () => window.clearTimeout(timer)
  }, [query, t, workspaceRoot])

  return (
    <aside className="ds-ide-search-sidebar flex h-full min-h-0 w-60 shrink-0 flex-col bg-ds-canvas">
      <div className="ds-surface-divider flex h-10 shrink-0 items-center gap-2 px-3">
        <Search className="h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.9} />
        <span className="truncate text-[12px] font-medium text-ds-ink">{t('ideWorkspaceSearchTitle')}</span>
      </div>
      <div className="ds-surface-divider shrink-0 px-2 py-2">
        <input
          type="search"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder={t('ideWorkspaceSearchPlaceholder')}
          className="h-8 w-full rounded-md border border-ds-border bg-ds-elevated px-2.5 text-[12.5px] text-ds-ink outline-none placeholder:text-ds-faint"
          autoFocus
          onKeyDown={(event) => {
            if (event.key !== 'Enter') return
            event.preventDefault()
            if (loading || query.trim() !== resultQuery) return
            const first = entries[0]
            if (first) onSelectFile(first.path)
          }}
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-1 py-1">
        {loading ? (
          <EditorListSkeleton rows={6} />
        ) : error ? (
          <p className="px-2 py-3 text-[12px] text-amber-700 dark:text-amber-200">{error}</p>
        ) : !query.trim() ? (
          <p className="px-2 py-3 text-[12px] text-ds-faint">{t('ideWorkspaceSearchHint')}</p>
        ) : entries.length === 0 ? (
          <p className="px-2 py-3 text-[12px] text-ds-faint">{t('ideWorkspaceSearchEmpty')}</p>
        ) : (
          <ul className="space-y-0.5">
            {entries.map((entry) => {
              const selected = selectedPath === entry.path
              const { name, parent } = splitFileNameAndParent(entry.path)
              return (
                <li key={entry.path}>
                  <button
                    type="button"
                    title={entry.path}
                    onClick={() => onSelectFile(entry.path)}
                    className={`flex h-7 w-full items-center gap-1.5 rounded-none px-2 text-left transition ${
                      selected
                        ? 'bg-ds-hover text-ds-ink'
                        : 'text-ds-muted hover:bg-ds-hover/60 hover:text-ds-ink'
                    }`}
                  >
                    <File className="h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.85} />
                    <span className="min-w-0 flex-1 truncate text-[12.5px]">
                      <span className="font-medium text-ds-ink">{name}</span>
                      {parent ? (
                        <span className="ml-1.5 text-[11px] text-ds-faint">{parent}</span>
                      ) : null}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
        {truncated && !loading ? (
          <p className="px-2 py-2 text-[11px] text-ds-faint">{t('ideWorkspaceSearchTruncated')}</p>
        ) : null}
      </div>
    </aside>
  )
}

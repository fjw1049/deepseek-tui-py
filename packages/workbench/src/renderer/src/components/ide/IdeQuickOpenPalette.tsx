import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactElement
} from 'react'
import { createPortal } from 'react-dom'
import { FileSearch, Search, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { formatShortcutLabel, shortcutChordTokens } from '@shared/shortcuts'
import type { WorkspaceTreeEntry } from '@shared/workspace-file'
import { splitFileNameAndParent } from '../../lib/editor-breadcrumb'
import { EditorListSkeleton } from '../workspace-editor/EditorListSkeleton'

type Props = {
  workspaceRoot: string
  onSelectFile: (path: string) => void
  onClose: () => void
}

const QUICK_OPEN_CHORD = { key: 'p' } as const

export function IdeQuickOpenPalette({
  workspaceRoot,
  onSelectFile,
  onClose
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const [query, setQuery] = useState('')
  const [entries, setEntries] = useState<WorkspaceTreeEntry[]>([])
  const [resultQuery, setResultQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestIdRef = useRef(0)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const listRef = useRef<HTMLUListElement | null>(null)
  const trimmedQuery = query.trim()

  useEffect(() => {
    const timer = window.setTimeout(() => inputRef.current?.focus(), 0)
    return () => window.clearTimeout(timer)
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    const root = workspaceRoot.trim()
    const trimmedQuery = query.trim()
    if (!root) {
      setEntries([])
      setResultQuery('')
      setError(null)
      setLoading(false)
      setActiveIndex(0)
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
            setError(result.message)
            return
          }
          setEntries(result.entries)
          setResultQuery(trimmedQuery)
          setError(null)
          setActiveIndex(0)
        })
        .catch((err: unknown) => {
          if (requestId !== requestIdRef.current) return
          setEntries([])
          setResultQuery(trimmedQuery)
          setError(err instanceof Error ? err.message : String(err))
        })
        .finally(() => {
          if (requestId === requestIdRef.current) setLoading(false)
        })
    }, trimmedQuery ? 120 : 0)

    return () => window.clearTimeout(timer)
  }, [query, t, workspaceRoot])

  useEffect(() => {
    const active = listRef.current?.querySelector<HTMLElement>('[aria-selected="true"]')
    active?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex, entries])

  const openActive = (): void => {
    if (loading || trimmedQuery !== resultQuery) return
    const entry = entries[activeIndex] ?? entries[0]
    if (!entry) return
    onSelectFile(entry.path)
  }

  const onInputKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>): void => {
    if (event.key === 'ArrowDown') {
      if (entries.length === 0) return
      event.preventDefault()
      setActiveIndex((index) => Math.min(entries.length - 1, index + 1))
      return
    }
    if (event.key === 'ArrowUp') {
      if (entries.length === 0) return
      event.preventDefault()
      setActiveIndex((index) => Math.max(0, index - 1))
      return
    }
    if (event.key !== 'Enter') return
    event.preventDefault()
    openActive()
  }

  const isEmpty = !loading && !error && entries.length === 0
  const shortcutLabel = formatShortcutLabel(QUICK_OPEN_CHORD)
  const shortcutTokens = shortcutChordTokens(QUICK_OPEN_CHORD)

  return createPortal(
    <div
      className="ds-modal-backdrop ds-endpoint-sheet-backdrop ds-search-modal-root ds-no-drag"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        className="ds-modal-surface ds-endpoint-sheet ds-search-modal ds-search-modal--quick-open"
        role="dialog"
        aria-modal="true"
        aria-label={t('ideWorkspaceSearchTitle')}
      >
        <div className="ds-search-modal__header">
          <Search className="ds-search-modal__search-icon" strokeWidth={1.75} aria-hidden />
          <input
            ref={inputRef}
            type="text"
            inputMode="search"
            enterKeyHint="search"
            role="searchbox"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onInputKeyDown}
            placeholder={t('ideWorkspaceSearchPlaceholder')}
            aria-label={t('ideWorkspaceSearchPlaceholder')}
            className="ds-search-modal__input"
            autoComplete="off"
            spellCheck={false}
          />
          <div className="ds-search-modal__header-right">
            <div className="ds-shortcut-keys shrink-0" aria-label={shortcutLabel}>
              {shortcutTokens.map((token, index) => (
                <kbd
                  key={`${token}-${index}`}
                  className={`ds-keycap${token.length > 1 ? ' ds-keycap--wide' : ''}`}
                >
                  {token}
                </kbd>
              ))}
            </div>
            <button
              type="button"
              className="ds-search-modal__close"
              onClick={onClose}
              aria-label={t('conversationSearchClose')}
            >
              <X className="h-3.5 w-3.5" strokeWidth={2} />
            </button>
          </div>
        </div>

        <div className={`ds-search-modal__body${isEmpty ? ' ds-search-modal__body--empty' : ''}`}>
          {loading ? (
            <EditorListSkeleton rows={5} />
          ) : error ? (
            <div className="ds-search-modal__empty">
              <p className="ds-search-modal__empty-title">{error}</p>
            </div>
          ) : isEmpty ? (
            <div className="ds-search-modal__empty">
              <FileSearch className="ds-search-modal__empty-icon" strokeWidth={1.5} aria-hidden />
              <p className="ds-search-modal__empty-title">
                {trimmedQuery
                  ? t('ideWorkspaceSearchEmpty')
                  : t('ideWorkspaceSearchIdleTitle')}
              </p>
            </div>
          ) : (
            <ul ref={listRef} className="ds-search-modal__list" role="listbox">
              {entries.map((entry, index) => {
                const active = index === activeIndex
                const { name, parent } = splitFileNameAndParent(entry.path)
                return (
                  <li key={entry.path}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={active}
                      title={entry.path}
                      className={`ds-search-modal__row ${
                        active ? 'ds-search-modal__row--active' : ''
                      }`}
                      onMouseEnter={() => setActiveIndex(index)}
                      onClick={() => onSelectFile(entry.path)}
                    >
                      <span className="ds-search-modal__row-main">
                        <span className="ds-search-modal__row-title">{name}</span>
                        {parent ? (
                          <span className="ds-search-modal__row-path">{parent}</span>
                        ) : null}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </div>
    </div>,
    document.body
  )
}

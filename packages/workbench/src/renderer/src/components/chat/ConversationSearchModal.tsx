import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactElement
} from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { Clock, CornerDownLeft, Folder, MessageSquare, Search, X } from 'lucide-react'
import { formatShortcutLabel, shortcutChordTokens } from '@shared/shortcuts'
import type { NormalizedThread } from '../../agent/types'
import { formatRelativeTime } from '../../lib/format-relative-time'
import { workspaceLabelFromPath } from '../../lib/workspace-label'

type Props = {
  open: boolean
  threads: NormalizedThread[]
  onClose: () => void
  onSelectThread: (id: string) => void
}

const RECENT_LIMIT = 40
const RESULT_LIMIT = 50

function threadMatchesQuery(thread: NormalizedThread, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return false
  if (thread.title.toLowerCase().includes(q)) return true
  const workspace = thread.workspace?.trim()
  if (!workspace) return false
  if (workspace.toLowerCase().includes(q)) return true
  return workspaceLabelFromPath(workspace).toLowerCase().includes(q)
}

function sortByRecent(threads: NormalizedThread[]): NormalizedThread[] {
  return [...threads].sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
}

export function ConversationSearchModal({
  open,
  threads,
  onClose,
  onSelectThread
}: Props): ReactElement | null {
  const { t, i18n } = useTranslation('common')
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)

  const trimmedQuery = query.trim()
  const browsingRecent = trimmedQuery.length === 0

  const recentThreads = useMemo(
    () => sortByRecent(threads).slice(0, RECENT_LIMIT),
    [threads]
  )

  const results = useMemo(() => {
    if (browsingRecent) return [] as NormalizedThread[]
    return sortByRecent(threads.filter((thread) => threadMatchesQuery(thread, trimmedQuery))).slice(
      0,
      RESULT_LIMIT
    )
  }, [threads, trimmedQuery, browsingRecent])

  const rows = browsingRecent ? recentThreads : results
  const rowCount = rows.length

  useEffect(() => {
    if (!open) return
    setQuery('')
    setActiveIndex(0)
    const timer = window.setTimeout(() => inputRef.current?.focus(), 0)
    return () => window.clearTimeout(timer)
  }, [open])

  useEffect(() => {
    setActiveIndex(0)
  }, [query, browsingRecent])

  useEffect(() => {
    const active = listRef.current?.querySelector<HTMLElement>('[aria-selected="true"]')
    active?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex, rows])

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  const selectThread = useCallback(
    (threadId: string) => {
      onSelectThread(threadId)
      onClose()
    },
    [onClose, onSelectThread]
  )

  const onInputKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>): void => {
    if (event.key === 'ArrowDown') {
      if (rowCount === 0) return
      event.preventDefault()
      setActiveIndex((index) => (index + 1) % rowCount)
      return
    }
    if (event.key === 'ArrowUp') {
      if (rowCount === 0) return
      event.preventDefault()
      setActiveIndex((index) => (index - 1 + rowCount) % rowCount)
      return
    }
    if (event.key !== 'Enter') return
    event.preventDefault()
    const thread = rows[activeIndex]
    if (thread) selectThread(thread.id)
  }

  if (!open) return null

  const shortcutChord = { key: 'k' } as const
  const shortcutLabel = formatShortcutLabel(shortcutChord)
  const shortcutTokens = shortcutChordTokens(shortcutChord)
  const isEmpty = rowCount === 0

  return createPortal(
    <div
      className="ds-modal-backdrop ds-endpoint-sheet-backdrop ds-search-modal-root ds-no-drag"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        className="ds-modal-surface ds-endpoint-sheet ds-search-modal"
        role="dialog"
        aria-modal="true"
        aria-label={t('conversationSearchTitle')}
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
            placeholder={t('conversationSearchPlaceholder')}
            aria-label={t('conversationSearchPlaceholder')}
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

        <div
          className={`ds-search-modal__body${isEmpty ? ' ds-search-modal__body--empty' : ''}`}
        >
          {isEmpty ? (
            <div className="ds-search-modal__empty">
              <Search className="ds-search-modal__empty-icon" strokeWidth={1.5} aria-hidden />
              <p className="ds-search-modal__empty-title">
                {browsingRecent
                  ? t('conversationSearchNoRecent')
                  : t('conversationSearchNoResults')}
              </p>
              <p className="ds-search-modal__empty-hint">{t('conversationSearchHint')}</p>
            </div>
          ) : (
            <>
              {browsingRecent ? (
                <div className="ds-search-modal__section">{t('conversationSearchRecent')}</div>
              ) : null}
              <ul ref={listRef} className="ds-search-modal__list" role="listbox">
                {rows.map((thread, index) => {
                  const workspace = thread.workspace?.trim()
                  const folder = workspace ? workspaceLabelFromPath(workspace) : ''
                  const active = index === activeIndex
                  return (
                    <li key={thread.id}>
                      <button
                        type="button"
                        role="option"
                        aria-selected={active}
                        className={`ds-search-modal__row ${
                          active ? 'ds-search-modal__row--active' : ''
                        }`}
                        onMouseEnter={() => setActiveIndex(index)}
                        onClick={() => selectThread(thread.id)}
                      >
                        <span className="ds-search-modal__row-icon-wrap" aria-hidden>
                          <MessageSquare strokeWidth={1.7} />
                        </span>
                        <span className="ds-search-modal__row-main">
                          <span className="ds-search-modal__row-title">{thread.title}</span>
                          <span className="ds-search-modal__row-meta">
                            {folder ? (
                              <span className="ds-search-modal__meta-chip">
                                <Folder strokeWidth={1.8} aria-hidden />
                                {folder}
                              </span>
                            ) : null}
                            <span className="ds-search-modal__meta-chip">
                              <Clock strokeWidth={1.8} aria-hidden />
                              {formatRelativeTime(thread.updatedAt, i18n.language)}
                            </span>
                          </span>
                        </span>
                        {active ? (
                          <CornerDownLeft
                            className="ds-search-modal__enter"
                            strokeWidth={1.75}
                            aria-hidden
                          />
                        ) : null}
                      </button>
                    </li>
                  )
                })}
              </ul>
            </>
          )}
        </div>

        {!isEmpty ? (
          <div className="ds-search-modal__footer" aria-hidden>
            <span>
              <kbd className="ds-keycap">↑</kbd>
              <kbd className="ds-keycap">↓</kbd>
              <span className="ds-search-modal__footer-label">
                {t('conversationSearchFooterSelect')}
              </span>
            </span>
            <span>
              <kbd className="ds-keycap">↵</kbd>
              <span className="ds-search-modal__footer-label">
                {t('conversationSearchFooterOpen')}
              </span>
            </span>
          </div>
        ) : null}
      </div>
    </div>,
    document.body
  )
}

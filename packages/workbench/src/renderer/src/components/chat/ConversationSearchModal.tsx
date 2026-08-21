import {
  Fragment,
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
import {
  Columns3,
  Folder,
  MessageSquare,
  Plus,
  Search,
  Settings,
  type LucideIcon
} from 'lucide-react'
import { shortcutChordTokens, type ShortcutChord } from '@shared/shortcuts'
import type { NormalizedThread } from '../../agent/types'
import { workspaceLabelFromPath } from '../../lib/workspace-label'

type Props = {
  open: boolean
  threads: NormalizedThread[]
  runtimeReady: boolean
  onClose: () => void
  onSelectThread: (id: string) => void
  onNewChat: () => void
  onAddProject: () => void
  onOpenKanban: () => void
  onOpenSettings: () => void
}

const RECENT_LIMIT = 16
const RESULT_LIMIT = 50

type ActionItem = {
  kind: 'action'
  id: string
  label: string
  shortcut: string
  icon: LucideIcon
  run: () => void
}

type ThreadItem = {
  kind: 'thread'
  id: string
  thread: NormalizedThread
}

type SearchItem = ActionItem | ThreadItem

type SearchSection = {
  id: string
  title: string
  items: SearchItem[]
}

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

function shortcutText(chord: ShortcutChord): string {
  return shortcutChordTokens(chord).join(' ')
}

function labelMatchesQuery(label: string, query: string): boolean {
  return label.toLowerCase().includes(query.trim().toLowerCase())
}

export function ConversationSearchModal({
  open,
  threads,
  runtimeReady,
  onClose,
  onSelectThread,
  onNewChat,
  onAddProject,
  onOpenKanban,
  onOpenSettings
}: Props): ReactElement | null {
  const { t } = useTranslation('common')
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)

  const trimmedQuery = query.trim()
  const browsingRecent = trimmedQuery.length === 0

  const actions = useMemo<ActionItem[]>(() => {
    const items: ActionItem[] = []
    if (runtimeReady) {
      items.push({
        kind: 'action',
        id: 'new-chat',
        label: t('newChat'),
        shortcut: shortcutText({ key: 'n' }),
        icon: Plus,
        run: onNewChat
      })
    }
    items.push(
      {
        kind: 'action',
        id: 'add-project',
        label: t('conversationSearchActionAddProject'),
        shortcut: shortcutText({ key: 'p' }),
        icon: Folder,
        run: onAddProject
      },
      {
        kind: 'action',
        id: 'kanban',
        label: t('kanbanNav'),
        shortcut: shortcutText({ key: 'j' }),
        icon: Columns3,
        run: onOpenKanban
      },
      {
        kind: 'action',
        id: 'settings',
        label: t('settings'),
        shortcut: '',
        icon: Settings,
        run: onOpenSettings
      }
    )
    return items
  }, [onAddProject, onNewChat, onOpenKanban, onOpenSettings, runtimeReady, t])

  const recentThreads = useMemo(
    () => sortByRecent(threads).slice(0, RECENT_LIMIT),
    [threads]
  )

  const resultThreads = useMemo(() => {
    if (browsingRecent) return [] as NormalizedThread[]
    return sortByRecent(threads.filter((thread) => threadMatchesQuery(thread, trimmedQuery))).slice(
      0,
      RESULT_LIMIT
    )
  }, [browsingRecent, threads, trimmedQuery])

  const sections = useMemo<SearchSection[]>(() => {
    const visibleActions = browsingRecent
      ? actions
      : actions.filter((action) => labelMatchesQuery(action.label, trimmedQuery))
    const threadItems: ThreadItem[] = (browsingRecent ? recentThreads : resultThreads).map(
      (thread) => ({
        kind: 'thread',
        id: thread.id,
        thread
      })
    )
    const next: SearchSection[] = []
    if (visibleActions.length > 0) {
      next.push({
        id: 'suggested',
        title: t('conversationSearchSuggested'),
        items: visibleActions
      })
    }
    if (threadItems.length > 0) {
      next.push({
        id: browsingRecent ? 'recent' : 'results',
        title: browsingRecent
          ? t('conversationSearchRecent')
          : t('conversationSearchResults'),
        items: threadItems
      })
    }
    return next
  }, [actions, browsingRecent, recentThreads, resultThreads, t, trimmedQuery])

  const flatItems = useMemo(
    () => sections.flatMap((section) => section.items),
    [sections]
  )
  const rowCount = flatItems.length
  const isEmpty = rowCount === 0
  const itemIndexById = useMemo(() => {
    const map = new Map<string, number>()
    flatItems.forEach((item, index) => map.set(item.id, index))
    return map
  }, [flatItems])

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
  }, [activeIndex, flatItems])

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

  const activateItem = useCallback(
    (item: SearchItem) => {
      if (item.kind === 'action') {
        onClose()
        item.run()
        return
      }
      onSelectThread(item.thread.id)
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
    const item = flatItems[activeIndex]
    if (item) activateItem(item)
  }

  if (!open) return null

  return createPortal(
    <div
      className="ds-modal-backdrop ds-endpoint-sheet-backdrop ds-search-modal-root ds-no-drag"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        className="ds-modal-surface ds-endpoint-sheet ds-search-modal ds-search-modal--palette"
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
        </div>

        <div className={`ds-search-modal__body${isEmpty ? ' ds-search-modal__body--empty' : ''}`}>
          {isEmpty ? (
            <div className="ds-search-modal__empty">
              <p className="ds-search-modal__empty-title">{t('conversationSearchNoResults')}</p>
            </div>
          ) : (
            <ul ref={listRef} className="ds-search-modal__list" role="listbox">
              {sections.map((section) => (
                <Fragment key={section.id}>
                  <li className="ds-search-modal__block" role="presentation">
                    <div className="ds-search-modal__section">{section.title}</div>
                  </li>
                  {section.items.map((item) => {
                    const index = itemIndexById.get(item.id) ?? 0
                    const active = index === activeIndex
                    const Icon = item.kind === 'action' ? item.icon : MessageSquare
                    const title = item.kind === 'action' ? item.label : item.thread.title
                    const trailing =
                      item.kind === 'action'
                        ? item.shortcut
                        : item.thread.workspace?.trim()
                          ? workspaceLabelFromPath(item.thread.workspace)
                          : ''
                    return (
                      <li key={item.id}>
                        <button
                          type="button"
                          role="option"
                          aria-selected={active}
                          className={`ds-search-modal__row${
                            active ? ' ds-search-modal__row--active' : ''
                          }`}
                          onMouseEnter={() => setActiveIndex(index)}
                          onClick={() => activateItem(item)}
                        >
                          <span className="ds-search-modal__row-icon-wrap" aria-hidden>
                            <Icon strokeWidth={1.7} />
                          </span>
                          <span className="ds-search-modal__row-title">{title}</span>
                          {trailing ? (
                            <span className="ds-search-modal__row-trailing">{trailing}</span>
                          ) : null}
                        </button>
                      </li>
                    )
                  })}
                </Fragment>
              ))}
            </ul>
          )}
        </div>

        <div className="ds-search-modal__footer">
          <span className="ds-search-modal__footer-hint">{t('conversationSearchFooterHint')}</span>
          <span className="ds-search-modal__footer-open">{t('conversationSearchFooterOpen')}</span>
        </div>
      </div>
    </div>,
    document.body
  )
}

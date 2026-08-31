import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactElement
} from 'react'
import { createPortal } from 'react-dom'
import {
  Check,
  ChevronDown,
  Folder,
  FolderOpen,
  LayoutGrid,
  Loader2,
  Plus,
  Search
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useComboboxNav } from '../../hooks/use-combobox-nav'
import { useLightDismiss } from '../../hooks/use-light-dismiss'
import { useChatStore } from '../../store/chat-store'
import { workspaceLabelFromPath } from '../../lib/workspace-label'
import {
  isChatsWorkspace,
  isClawWorkspacePath,
  isInternalTemporaryWorkspace,
  normalizeWorkspaceRoot
} from '../../lib/workspace-path'

type Props = {
  workspaceRoot: string
  usePortal?: boolean
  menuPlacement?: 'above' | 'below'
  /** Compact tray: drop the chevron before the project chip itself. */
  hideChevron?: boolean
  /** Composer tray: 15px. Embedded IDE rail stays dense. */
  size?: 'dense' | 'tray'
}

const MENU_WIDTH = 340
const RECENT_LIMIT = 4

type ProjectGroup = {
  id: string
  label: string | null
  items: ProjectOption[]
}

type ProjectOption = {
  path: string
  label: string
}

function projectPathHint(path: string): string {
  const normalized = path.replace(/\\/g, '/').replace(/\/+$/, '')
  const parts = normalized.split('/').filter(Boolean)
  if (parts.length <= 1) return normalized
  const parent = parts.slice(0, -1).join('/')
  const withSlash = normalized.startsWith('/') ? `/${parent}` : parent
  // Truncate long parents from the left while keeping the end readable.
  if (withSlash.length > 42) {
    return `…${withSlash.slice(-40)}`
  }
  return withSlash
}

export function ProjectContextPicker({
  workspaceRoot,
  usePortal = false,
  menuPlacement = 'above',
  hideChevron = false,
  size = 'dense'
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const threads = useChatStore((s) => s.threads)
  const settingsWorkspaceRoot = useChatStore((s) => s.workspaceRoot)
  const activateWorkspace = useChatStore((s) => s.activateWorkspace)
  const chooseWorkspace = useChatStore((s) => s.chooseWorkspace)
  const createThread = useChatStore((s) => s.createThread)
  const runtimeReady = useChatStore((s) => s.runtimeConnection) === 'ready'

  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [acting, setActing] = useState(false)
  const [menuStyle, setMenuStyle] = useState<CSSProperties>({})
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const listId = useId()

  const activePath = normalizeWorkspaceRoot(workspaceRoot)
  const isTemporary = isChatsWorkspace(workspaceRoot) || !activePath
  const triggerLabel = isTemporary
    ? t('contextBarWorkInProject')
    : workspaceLabelFromPath(activePath) || activePath

  const projectOptions = useMemo(() => {
    const seen = new Set<string>()
    const options: ProjectOption[] = []
    const consider = (raw: string | undefined): void => {
      const path = normalizeWorkspaceRoot(raw)
      if (
        !path ||
        seen.has(path) ||
        isChatsWorkspace(path) ||
        isInternalTemporaryWorkspace(path) ||
        isClawWorkspacePath(path)
      ) {
        return
      }
      seen.add(path)
      options.push({ path, label: workspaceLabelFromPath(path) || path })
    }

    for (const thread of threads) {
      consider(thread.workspace)
    }
    consider(settingsWorkspaceRoot)
    consider(activePath)

    options.sort((a, b) => a.label.localeCompare(b.label))
    return options
  }, [activePath, settingsWorkspaceRoot, threads])

  const filteredProjects = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return projectOptions
    return projectOptions.filter(
      (item) => item.label.toLowerCase().includes(q) || item.path.toLowerCase().includes(q)
    )
  }, [projectOptions, query])

  const projectGroups = useMemo<ProjectGroup[]>(() => {
    const searching = query.trim().length > 0
    if (searching || filteredProjects.length < 3) {
      return [{ id: 'all', label: null, items: filteredProjects }]
    }
    const ranked = [...threads].sort(
      (a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt)
    )
    const recentPaths: string[] = []
    const seen = new Set<string>()
    for (const thread of ranked) {
      const path = normalizeWorkspaceRoot(thread.workspace)
      if (
        !path ||
        seen.has(path) ||
        isChatsWorkspace(path) ||
        isInternalTemporaryWorkspace(path) ||
        isClawWorkspacePath(path)
      ) {
        continue
      }
      seen.add(path)
      recentPaths.push(path)
      if (recentPaths.length >= RECENT_LIMIT) break
    }
    const recentSet = new Set(recentPaths)
    const recent = recentPaths
      .map((path) => filteredProjects.find((item) => item.path === path))
      .filter((item): item is ProjectOption => item != null)
    const rest = filteredProjects.filter((item) => !recentSet.has(item.path))
    if (recent.length === 0 || rest.length === 0) {
      return [{ id: 'all', label: null, items: filteredProjects }]
    }
    return [
      { id: 'recent', label: t('contextBarRecentProjects'), items: recent },
      { id: 'all', label: t('contextBarAllProjects'), items: rest }
    ]
  }, [filteredProjects, query, t, threads])

  const flatProjects = useMemo(
    () => projectGroups.flatMap((group) => group.items),
    [projectGroups]
  )
  const nav = useComboboxNav(flatProjects.length, open)

  useEffect(() => {
    setOpen(false)
    setQuery('')
    setActing(false)
  }, [activePath])

  useEffect(() => {
    if (!open) return
    window.setTimeout(() => inputRef.current?.focus(), 0)
  }, [open])

  useEffect(() => {
    if (!open) return
    const row = menuRef.current?.querySelector(`[data-combobox-index="${nav.highlighted}"]`)
    row?.scrollIntoView({ block: 'nearest' })
  }, [nav.highlighted, open])

  const updateMenuPosition = useCallback((): void => {
    const trigger = triggerRef.current
    if (!trigger) return
    const rect = trigger.getBoundingClientRect()
    const width = Math.min(MENU_WIDTH, window.innerWidth - 24)
    const left = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))

    if (usePortal) {
      if (menuPlacement === 'below') {
        setMenuStyle({
          position: 'fixed',
          left,
          top: rect.bottom + 8,
          width,
          zIndex: 120
        })
        return
      }
      setMenuStyle({
        position: 'fixed',
        left,
        bottom: window.innerHeight - rect.top + 8,
        width,
        zIndex: 120
      })
      return
    }

    setMenuStyle({
      position: 'absolute',
      left: 0,
      width: `min(${MENU_WIDTH}px, calc(100vw - 48px))`,
      ...(menuPlacement === 'below'
        ? { top: 'calc(100% + 8px)' }
        : { bottom: 'calc(100% + 8px)' })
    })
  }, [menuPlacement, usePortal])

  useLayoutEffect(() => {
    if (!open) return
    updateMenuPosition()
    window.addEventListener('resize', updateMenuPosition)
    window.addEventListener('scroll', updateMenuPosition, true)
    return () => {
      window.removeEventListener('resize', updateMenuPosition)
      window.removeEventListener('scroll', updateMenuPosition, true)
    }
  }, [open, updateMenuPosition])

  useLightDismiss({
    open,
    onDismiss: () => setOpen(false),
    refs: [wrapRef, menuRef]
  })

  const selectProject = async (path: string): Promise<void> => {
    if (!runtimeReady || acting) return
    if (normalizeWorkspaceRoot(path) === activePath && !isTemporary) {
      setOpen(false)
      return
    }
    setActing(true)
    try {
      await activateWorkspace(path)
      setOpen(false)
      setQuery('')
    } finally {
      setActing(false)
    }
  }

  const createNewProject = async (): Promise<void> => {
    if (!runtimeReady || acting) return
    setActing(true)
    try {
      setOpen(false)
      await chooseWorkspace({ createThreadAfter: true })
    } finally {
      setActing(false)
    }
  }

  const clearProject = async (): Promise<void> => {
    if (!runtimeReady || acting) return
    if (isTemporary) {
      setOpen(false)
      return
    }
    setActing(true)
    try {
      await createThread({ chats: true })
      setOpen(false)
      setQuery('')
    } finally {
      setActing(false)
    }
  }

  const menu = open ? (
    <div
      ref={menuRef}
      style={menuStyle}
      className={`ds-project-context-menu ds-morph-pop z-50 overflow-hidden ${
        menuPlacement === 'below' ? 'ds-morph-pop--below' : ''
      }`}
      onMouseDown={(event) => event.stopPropagation()}
    >
      <div className="ds-project-context-menu__header">
        <label className="ds-project-context-menu__search">
          <Search className="h-3.5 w-3.5 shrink-0 opacity-45" strokeWidth={1.85} aria-hidden />
          <input
            ref={inputRef}
            role="combobox"
            aria-expanded={open}
            aria-controls={listId}
            aria-autocomplete="list"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                e.preventDefault()
                setOpen(false)
                return
              }
              nav.onKeyDown(e, (index) => {
                const item = flatProjects[index]
                if (item) void selectProject(item.path)
              })
            }}
            placeholder={t('contextBarSearchProjects')}
            className="ds-project-context-menu__search-input"
          />
        </label>
      </div>

      <div id={listId} role="listbox" className="ds-project-context-menu__list">
        {flatProjects.length === 0 ? (
          <div className="ds-project-context-menu__empty">{t('contextBarNoMatchingProjects')}</div>
        ) : (
          (() => {
            let flatIndex = 0
            return projectGroups.map((group) => (
              <div key={group.id}>
                {group.label ? (
                  <div className="ds-project-context-menu__group-label">{group.label}</div>
                ) : null}
                {group.items.map((item) => {
                  const index = flatIndex++
                  const selected = !isTemporary && item.path === activePath
                  const highlighted = index === nav.highlighted
                  return (
                    <button
                      key={item.path}
                      type="button"
                      role="option"
                      aria-selected={selected}
                      data-combobox-index={index}
                      disabled={acting}
                      className={`ds-project-context-menu__row ${
                        selected ? 'ds-project-context-menu__row--active' : ''
                      } ${highlighted ? 'ds-project-context-menu__row--highlight' : ''}`}
                      onMouseEnter={() => nav.setHighlighted(index)}
                      onClick={() => void selectProject(item.path)}
                    >
                      <span className="ds-project-context-menu__icon" aria-hidden>
                        <Folder className="h-3.5 w-3.5" strokeWidth={1.85} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="ds-project-context-menu__row-title">{item.label}</span>
                        <span className="ds-project-context-menu__row-path" title={item.path}>
                          {projectPathHint(item.path)}
                        </span>
                      </span>
                      {selected ? (
                        <Check className="h-4 w-4 shrink-0 text-accent" strokeWidth={2.2} />
                      ) : null}
                    </button>
                  )
                })}
              </div>
            ))
          })()
        )}
      </div>

      <div className="ds-project-context-menu__footer">
        <button
          type="button"
          disabled={acting || !runtimeReady}
          className="ds-project-context-menu__row"
          onClick={() => void createNewProject()}
        >
          <span className="ds-project-context-menu__icon" aria-hidden>
            {acting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} />
            ) : (
              <Plus className="h-3.5 w-3.5" strokeWidth={1.9} />
            )}
          </span>
          <span className="ds-project-context-menu__row-title">{t('contextBarNewProject')}</span>
        </button>
        <button
          type="button"
          disabled={acting || !runtimeReady}
          className={`ds-project-context-menu__row ${
            isTemporary ? 'ds-project-context-menu__row--active' : ''
          }`}
          onClick={() => void clearProject()}
        >
          <span className="ds-project-context-menu__icon" aria-hidden>
            <LayoutGrid className="h-3.5 w-3.5" strokeWidth={1.9} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="ds-project-context-menu__row-title">{t('contextBarNoProject')}</span>
          </span>
          {isTemporary ? (
            <Check className="h-4 w-4 shrink-0 text-accent" strokeWidth={2.2} />
          ) : null}
        </button>
      </div>
    </div>
  ) : null

  return (
    <div ref={wrapRef} className="ds-no-drag relative min-w-0">
      <button
        ref={triggerRef}
        type="button"
        className={
          size === 'tray'
            ? `ds-workspace-context-chip ds-workspace-context-chip--tray flex max-w-[240px] items-center rounded-md py-1 text-left sm:max-w-[280px] ${
                isTemporary
                  ? 'ds-workspace-context-chip--prompt h-[30px] gap-[7px] px-2'
                  : 'h-8 gap-2 px-2.5'
              }`
            : 'ds-workspace-context-chip flex h-7 max-w-[180px] items-center gap-1.5 rounded-md px-2 py-1 text-left sm:max-w-[220px]'
        }
        onClick={() => setOpen((v) => !v)}
        title={isTemporary ? t('contextBarWorkInProject') : activePath}
        aria-expanded={open}
      >
        {isTemporary ? (
          <FolderOpen
            className={
              size === 'tray'
                ? 'ds-workspace-context-chip__prompt-icon h-[15px] w-[15px] shrink-0'
                : 'h-3.5 w-3.5 shrink-0'
            }
            strokeWidth={size === 'tray' ? 1.6 : 1.7}
          />
        ) : (
          <Folder className={size === 'tray' ? 'h-4 w-4 shrink-0' : 'h-3.5 w-3.5 shrink-0'} strokeWidth={1.7} />
        )}
        <span
          className={`min-w-0 flex-1 truncate ${
            size === 'tray' ? (isTemporary ? 'leading-5' : 'text-[15px]') : ''
          }`}
        >
          {triggerLabel}
        </span>
        {!hideChevron ? (
          <ChevronDown
            className={`ds-workspace-context-chip__chevron ${
              size === 'tray' ? (isTemporary ? 'h-3 w-3' : 'h-3.5 w-3.5') : ''
            }`}
            strokeWidth={isTemporary && size === 'tray' ? 2 : 2.2}
          />
        ) : null}
      </button>
      {usePortal && typeof document !== 'undefined' ? createPortal(menu, document.body) : menu}
    </div>
  )
}

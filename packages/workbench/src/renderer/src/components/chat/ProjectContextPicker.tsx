import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactElement
} from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, Folder, Import, LayoutGrid, Loader2, Plus, Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'
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
}

const MENU_WIDTH = 340

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
  menuPlacement = 'above'
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

  useEffect(() => {
    setOpen(false)
    setQuery('')
    setActing(false)
  }, [activePath])

  useEffect(() => {
    if (!open) return
    window.setTimeout(() => inputRef.current?.focus(), 0)
  }, [open])

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

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: PointerEvent): void => {
      const target = event.target
      if (!(target instanceof Node)) return
      if (wrapRef.current?.contains(target)) return
      if (menuRef.current?.contains(target)) return
      setOpen(false)
    }
    const timer = window.setTimeout(() => {
      window.addEventListener('pointerdown', onPointerDown, true)
    }, 0)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('pointerdown', onPointerDown, true)
    }
  }, [open])

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
      className="ds-project-context-menu z-50 overflow-hidden"
      onMouseDown={(event) => event.stopPropagation()}
    >
      <div className="ds-project-context-menu__header">
        <label className="ds-project-context-menu__search">
          <Search className="h-3.5 w-3.5 shrink-0 opacity-45" strokeWidth={1.85} aria-hidden />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                e.preventDefault()
                setOpen(false)
              }
            }}
            placeholder={t('contextBarSearchProjects')}
            className="ds-project-context-menu__search-input"
          />
        </label>
      </div>

      <div className="ds-project-context-menu__list">
        {filteredProjects.length === 0 ? (
          <div className="ds-project-context-menu__empty">{t('contextBarNoMatchingProjects')}</div>
        ) : (
          filteredProjects.map((item) => {
            const selected = !isTemporary && item.path === activePath
            return (
              <button
                key={item.path}
                type="button"
                disabled={acting}
                className={`ds-project-context-menu__row ${
                  selected ? 'ds-project-context-menu__row--active' : ''
                }`}
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
          })
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
        className="ds-workspace-context-chip flex h-7 max-w-[180px] items-center gap-1.5 rounded-md px-2 py-1 text-left sm:max-w-[220px]"
        onClick={() => setOpen((v) => !v)}
        title={isTemporary ? t('contextBarWorkInProject') : activePath}
        aria-expanded={open}
      >
        {isTemporary ? (
          <Import className="h-3.5 w-3.5 shrink-0" strokeWidth={1.7} />
        ) : (
          <Folder className="h-3.5 w-3.5 shrink-0" strokeWidth={1.7} />
        )}
        <span className="min-w-0 flex-1 truncate">{triggerLabel}</span>
        <ChevronDown className="ds-workspace-context-chip__chevron" strokeWidth={2.2} />
      </button>
      {usePortal && typeof document !== 'undefined' ? createPortal(menu, document.body) : menu}
    </div>
  )
}

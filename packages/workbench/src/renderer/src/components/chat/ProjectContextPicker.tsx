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
import { Check, ChevronDown, Folder, LayoutGrid, Loader2, Plus, Search } from 'lucide-react'
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

const MENU_WIDTH = 360

type ProjectOption = {
  path: string
  label: string
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
      className="z-50 overflow-hidden rounded-2xl border border-ds-border bg-ds-elevated/92 shadow-[0_24px_70px_rgba(44,55,78,0.18)] backdrop-blur-xl dark:shadow-[0_30px_80px_rgba(0,0,0,0.42)]"
      onMouseDown={(event) => event.stopPropagation()}
    >
      <div className="flex items-center gap-2 border-b border-ds-border-muted px-3 py-2.5">
        <Search className="h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.8} />
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
          className="min-w-0 flex-1 bg-transparent text-[13px] text-ds-ink outline-none placeholder:text-ds-faint"
        />
      </div>

      <div className="max-h-[280px] overflow-y-auto px-2 py-2">
        {filteredProjects.length === 0 ? (
          <div className="px-2 py-3 text-[12.5px] text-ds-faint">{t('contextBarNoMatchingProjects')}</div>
        ) : (
          filteredProjects.map((item) => {
            const selected = !isTemporary && item.path === activePath
            return (
              <button
                key={item.path}
                type="button"
                disabled={acting}
                className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left text-ds-ink transition hover:bg-ds-hover disabled:opacity-50"
                onClick={() => void selectProject(item.path)}
              >
                <Folder className="h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.8} />
                <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{item.label}</span>
                {selected ? (
                  <Check className="h-3.5 w-3.5 shrink-0 text-ds-muted" strokeWidth={2} />
                ) : null}
              </button>
            )
          })
        )}
      </div>

      <div className="space-y-0.5 border-t border-ds-border-muted px-2 py-2">
        <button
          type="button"
          disabled={acting || !runtimeReady}
          className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left text-[13px] font-medium text-ds-ink transition hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-45"
          onClick={() => void createNewProject()}
        >
          {acting ? (
            <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-ds-muted" strokeWidth={2} />
          ) : (
            <Plus className="h-3.5 w-3.5 shrink-0 text-ds-muted" strokeWidth={1.9} />
          )}
          <span className="min-w-0 truncate">{t('contextBarNewProject')}</span>
        </button>
        <button
          type="button"
          disabled={acting || !runtimeReady}
          className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left text-[13px] font-medium text-ds-ink transition hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-45"
          onClick={() => void clearProject()}
        >
          <LayoutGrid className="h-3.5 w-3.5 shrink-0 text-ds-muted" strokeWidth={1.9} />
          <span className="min-w-0 truncate">{t('contextBarNoProject')}</span>
          {isTemporary ? (
            <Check className="ml-auto h-3.5 w-3.5 shrink-0 text-ds-muted" strokeWidth={2} />
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
        <Folder className="h-3.5 w-3.5 shrink-0" strokeWidth={1.7} />
        <span className="min-w-0 flex-1 truncate">{triggerLabel}</span>
        <ChevronDown className="ds-workspace-context-chip__chevron" strokeWidth={2.2} />
      </button>
      {usePortal && typeof document !== 'undefined' ? createPortal(menu, document.body) : menu}
    </div>
  )
}

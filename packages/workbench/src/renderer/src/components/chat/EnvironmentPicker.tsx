import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactElement
} from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, FolderGit2, Laptop } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useLightDismiss } from '../../hooks/use-light-dismiss'
import { useChatStore } from '../../store/chat-store'
import {
  resolveWorkspaceEnvMode,
  useEnvironmentPreferences,
  type ThreadEnvMode
} from '../../store/environment-preferences'
import { isChatsWorkspace, normalizeWorkspaceRoot } from '../../lib/workspace-path'

type Props = {
  workspaceRoot: string
  usePortal?: boolean
  menuPlacement?: 'above' | 'below'
  /** Compact tray: drop the chevron. */
  hideChevron?: boolean
  /** Composer tray: 15px. Embedded IDE rail stays dense. */
  size?: 'dense' | 'tray'
}

const MENU_WIDTH = 240
const MENU_GAP = 8
const VIEWPORT_GUTTER = 12

/** Body zooms with the UI scale, while trigger rectangles use viewport pixels. */
function readUiScale(): number {
  const scale = parseFloat(
    getComputedStyle(document.documentElement).getPropertyValue('--ds-ui-scale')
  )
  return Number.isFinite(scale) && scale > 0 ? scale : 1
}

/**
 * Local/Worktree chip between the project and branch pickers. Edits apply
 * only before a thread's first turn; afterwards the chip is read-only
 * (the runtime rejects the change).
 */
export function EnvironmentPicker({
  workspaceRoot,
  usePortal = false,
  menuPlacement = 'above',
  hideChevron = false,
  size = 'dense'
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const threads = useChatStore((s) => s.threads)
  const updateThread = useChatStore((s) => s.updateThreadEnvMode)
  const modeByWorkspace = useEnvironmentPreferences((s) => s.modeByWorkspace)
  const setEnvMode = useEnvironmentPreferences((s) => s.setEnvMode)

  const [open, setOpen] = useState(false)
  const [acting, setActing] = useState(false)
  const [menuStyle, setMenuStyle] = useState<CSSProperties>({})
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)

  const activeThread = activeThreadId
    ? threads.find((thread) => thread.id === activeThreadId) ?? null
    : null
  const normalizedRoot = normalizeWorkspaceRoot(workspaceRoot)
  // A thread without turns still follows the remembered workspace preference;
  // only a thread that already ran a turn pins its own env mode.
  const committed =
    activeThread && activeThread.latestTurnId ? activeThread.envMode ?? 'local' : null
  const mode: ThreadEnvMode =
    committed ??
    (activeThread ? activeThread.envMode ?? 'local' : resolveWorkspaceEnvMode(modeByWorkspace, normalizedRoot))
  const locked = committed != null
  const isTemporary = isChatsWorkspace(workspaceRoot) || !normalizedRoot
  const label = mode === 'worktree' ? t('envPickerWorktree') : t('envPickerLocal')

  const updateMenuPosition = useCallback((): void => {
    const trigger = triggerRef.current
    if (!trigger) return
    const rect = trigger.getBoundingClientRect()
    const scale = usePortal ? readUiScale() : 1
    const viewportWidth = window.innerWidth / scale
    const viewportHeight = window.innerHeight / scale
    const triggerLeft = rect.left / scale
    const triggerTop = rect.top / scale
    const triggerBottom = rect.bottom / scale
    const width = Math.min(MENU_WIDTH, viewportWidth - VIEWPORT_GUTTER * 2)
    const left = Math.max(
      VIEWPORT_GUTTER,
      Math.min(triggerLeft, viewportWidth - width - VIEWPORT_GUTTER)
    )

    if (usePortal) {
      if (menuPlacement === 'below') {
        setMenuStyle({
          position: 'fixed',
          left,
          top: triggerBottom + MENU_GAP,
          width,
          zIndex: 120
        })
        return
      }
      setMenuStyle({
        position: 'fixed',
        left,
        bottom: viewportHeight - triggerTop + MENU_GAP,
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

  useEffect(() => {
    setOpen(false)
    setActing(false)
  }, [normalizedRoot])

  const selectMode = async (next: ThreadEnvMode): Promise<void> => {
    if (locked || acting || next === mode) {
      setOpen(false)
      return
    }
    setActing(true)
    try {
      if (activeThread && !activeThread.latestTurnId) {
        await updateThread(next)
      } else if (!activeThread) {
        setEnvMode(normalizedRoot, next)
      }
      setOpen(false)
    } finally {
      setActing(false)
    }
  }

  const menu = open ? (
    <div
      ref={menuRef}
      style={menuStyle}
      className="ds-project-context-menu ds-morph-pop z-50 flex flex-col overflow-hidden"
      onMouseDown={(event) => event.stopPropagation()}
    >
      <div className="ds-project-context-menu__group-label shrink-0 px-3 pt-2">
        {t('envPickerLabel')}
      </div>
      <div className="min-h-0 pb-1">
        {(
          [
            { mode: 'local' as const, icon: Laptop, label: t('envPickerLocal') },
            { mode: 'worktree' as const, icon: FolderGit2, label: t('envPickerWorktree') }
          ] as const
        ).map(({ mode: itemMode, icon: Icon, label: itemLabel }) => (
          <button
            key={itemMode}
            type="button"
            disabled={locked || acting}
            className={`ds-project-context-menu__row ${
              mode === itemMode ? 'ds-project-context-menu__row--active' : ''
            }`}
            title={locked ? undefined : itemLabel}
            onClick={() => void selectMode(itemMode)}
          >
            <span className="ds-project-context-menu__icon" aria-hidden>
              <Icon className="h-3.5 w-3.5" strokeWidth={1.85} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="ds-project-context-menu__row-title">{itemLabel}</span>
            </span>
            {mode === itemMode ? (
              <Check className="h-4 w-4 shrink-0 text-accent" strokeWidth={2.2} />
            ) : null}
          </button>
        ))}
      </div>
    </div>
  ) : null

  return (
    <div ref={wrapRef} className="ds-no-drag relative min-w-0">
      <button
        ref={triggerRef}
        type="button"
        disabled={locked}
        className={
          size === 'tray'
            ? 'ds-workspace-context-chip ds-workspace-context-chip--tray flex h-7 max-w-[160px] items-center gap-1.5 rounded-md px-2 py-1 text-left'
            : 'ds-workspace-context-chip flex h-7 max-w-[140px] items-center gap-1.5 rounded-md px-2 py-1 text-left'
        }
        onClick={() => setOpen((v) => !v)}
        title={label}
        aria-expanded={open}
      >
        {mode === 'worktree' ? (
          <FolderGit2 className={size === 'tray' ? 'h-4 w-4 shrink-0' : 'h-3.5 w-3.5 shrink-0'} strokeWidth={1.7} />
        ) : (
          <Laptop className={size === 'tray' ? 'h-4 w-4 shrink-0' : 'h-3.5 w-3.5 shrink-0'} strokeWidth={1.7} />
        )}
        <span
          className={`min-w-0 flex-1 truncate ${size === 'tray' ? 'text-[14px]' : ''}`}
        >
          {label}
        </span>
        {!hideChevron && !locked ? (
          <ChevronDown
            className={`ds-workspace-context-chip__chevron ${size === 'tray' ? 'h-3.5 w-3.5' : ''}`}
            strokeWidth={2.2}
          />
        ) : null}
      </button>
      {usePortal && typeof document !== 'undefined' ? createPortal(menu, document.body) : menu}
    </div>
  )
}

import { useLayoutEffect, useRef, useState, type CSSProperties, type ReactElement } from 'react'
import { createPortal } from 'react-dom'
import {
  Archive,
  Copy,
  ExternalLink,
  FolderOpen,
  Hash,
  MailWarning,
  Pencil,
  Pin,
  PinOff,
  Terminal,
  Trash2
} from 'lucide-react'
import { ContextMenuColorBar } from './ContextMenuColorBar'
import { useLightDismiss } from '../../hooks/use-light-dismiss'
import { usePreferredEditorLabel } from '../../hooks/use-preferred-editor-label'
import type { SidebarLabelColor } from '../../lib/sidebar-chrome'

export type ThreadContextMenuAction =
  | 'rename'
  | 'toggle-pin'
  | 'archive'
  | 'mark-unread'
  | 'copy-path'
  | 'copy-relative-path'
  | 'open-with-editor'
  | 'reveal-in-folder'
  | 'open-terminal'
  | 'copy-thread-id'
  | 'delete'

type ThreadContextMenuProps = {
  x: number
  y: number
  /** Grow the menu upward from (x, y) instead of downward. */
  openUp?: boolean
  pinned: boolean
  canMarkUnread: boolean
  hasPath: boolean
  labelColor: SidebarLabelColor
  onLabelColorChange: (color: SidebarLabelColor) => void
  onAction: (action: ThreadContextMenuAction) => void
  onClose: () => void
  t: (k: string, opts?: Record<string, unknown>) => string
}

const MENU_WIDTH = 240

export function ThreadContextMenu({
  x,
  y,
  openUp = false,
  pinned,
  canMarkUnread,
  hasPath,
  labelColor,
  onLabelColorChange,
  onAction,
  onClose,
  t
}: ThreadContextMenuProps): ReactElement | null {
  const menuRef = useRef<HTMLDivElement | null>(null)
  const editorLabel = usePreferredEditorLabel(t('threadMenuEditorFallback'))
  const [style, setStyle] = useState<CSSProperties>({
    position: 'fixed',
    left: x,
    top: y,
    width: MENU_WIDTH,
    zIndex: 130,
    visibility: 'hidden'
  })

  useLayoutEffect(() => {
    const el = menuRef.current
    if (!el) return
    // The app applies `zoom: var(--ds-ui-scale)` to <body>. Because this menu is
    // portaled into <body>, that zoom rescales our fixed coordinates — but the
    // incoming clientX/clientY are pre-zoom viewport coords. Divide by the scale
    // so the menu lands exactly at the cursor regardless of the UI scale setting.
    const scale =
      parseFloat(
        getComputedStyle(document.documentElement).getPropertyValue('--ds-ui-scale')
      ) || 1
    // getBoundingClientRect already reports post-zoom (scaled) pixels, so convert
    // the measured menu box back to the unscaled space used for clamping.
    const rectW = el.offsetWidth
    const rectH = el.offsetHeight
    const ax = x / scale
    const ay = y / scale
    const viewW = window.innerWidth / scale
    const viewH = window.innerHeight / scale
    const left = Math.max(8, Math.min(ax, viewW - rectW - 8))
    // Chats rows open upward (menu bottom anchored at y); others drop downward.
    const desiredTop = openUp ? ay - rectH : ay
    const top = Math.max(8, Math.min(desiredTop, viewH - rectH - 8))
    setStyle({ position: 'fixed', left, top, width: MENU_WIDTH, zIndex: 130 })
  }, [x, y, openUp, editorLabel])

  useLightDismiss({
    open: true,
    onDismiss: onClose,
    refs: [menuRef]
  })

  const run = (action: ThreadContextMenuAction): void => {
    onAction(action)
    onClose()
  }

  const itemClass =
    'flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13px] text-ds-ink transition-colors duration-150 hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent'
  const iconClass = 'h-3.5 w-3.5 shrink-0 text-ds-faint'

  const menu = (
    <div
      ref={menuRef}
      style={style}
      className="ds-no-drag overflow-hidden rounded-xl border border-ds-border bg-ds-elevated p-1 shadow-[0_24px_70px_rgba(44,55,78,0.18)] backdrop-blur-xl dark:shadow-[0_30px_80px_rgba(0,0,0,0.42)]"
      onMouseDown={(event) => event.stopPropagation()}
    >
      <button type="button" className={itemClass} onClick={() => run('rename')}>
        <Pencil className={iconClass} strokeWidth={1.8} />
        <span className="min-w-0 truncate">{t('threadMenuRename')}</span>
      </button>
      <button type="button" className={itemClass} onClick={() => run('toggle-pin')}>
        {pinned ? (
          <PinOff className={iconClass} strokeWidth={1.8} />
        ) : (
          <Pin className={iconClass} strokeWidth={1.8} />
        )}
        <span className="min-w-0 truncate">
          {pinned ? t('sidebarUnpinThread') : t('sidebarPinThread')}
        </span>
      </button>
      <button type="button" className={itemClass} onClick={() => run('archive')}>
        <Archive className={iconClass} strokeWidth={1.8} />
        <span className="min-w-0 truncate">{t('sidebarThreadArchive')}</span>
      </button>
      <button
        type="button"
        className={itemClass}
        onClick={() => run('mark-unread')}
        disabled={!canMarkUnread}
      >
        <MailWarning className={iconClass} strokeWidth={1.8} />
        <span className="min-w-0 truncate">{t('threadMenuMarkUnread')}</span>
      </button>

      <div className="my-1 h-px bg-ds-border-muted" />

      <button
        type="button"
        className={itemClass}
        onClick={() => run('copy-path')}
        disabled={!hasPath}
      >
        <Copy className={iconClass} strokeWidth={1.8} />
        <span className="min-w-0 truncate">{t('threadMenuCopyPath')}</span>
      </button>
      <button
        type="button"
        className={itemClass}
        onClick={() => run('copy-relative-path')}
        disabled={!hasPath}
      >
        <Copy className={iconClass} strokeWidth={1.8} />
        <span className="min-w-0 truncate">{t('threadMenuCopyRelativePath')}</span>
      </button>
      <button
        type="button"
        className={itemClass}
        onClick={() => run('open-with-editor')}
        disabled={!hasPath}
      >
        <ExternalLink className={iconClass} strokeWidth={1.8} />
        <span className="min-w-0 truncate">
          {t('workspaceEditorOpenExternal', { editor: editorLabel })}
        </span>
      </button>
      <button
        type="button"
        className={itemClass}
        onClick={() => run('reveal-in-folder')}
        disabled={!hasPath}
      >
        <FolderOpen className={iconClass} strokeWidth={1.8} />
        <span className="min-w-0 truncate">{t('threadMenuRevealInFolder')}</span>
      </button>
      <button
        type="button"
        className={itemClass}
        onClick={() => run('open-terminal')}
        disabled={!hasPath}
      >
        <Terminal className={iconClass} strokeWidth={1.8} />
        <span className="min-w-0 truncate">{t('threadMenuOpenTerminal')}</span>
      </button>
      <button type="button" className={itemClass} onClick={() => run('copy-thread-id')}>
        <Hash className={iconClass} strokeWidth={1.8} />
        <span className="min-w-0 truncate">{t('threadMenuCopyThreadId')}</span>
      </button>

      <div className="my-1 h-px bg-ds-border-muted" />

      <button
        type="button"
        className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13px] text-red-600 transition-colors duration-150 hover:bg-red-500/10 dark:text-red-400"
        onClick={() => run('delete')}
      >
        <Trash2 className="h-3.5 w-3.5 shrink-0" strokeWidth={1.8} />
        <span className="min-w-0 truncate">{t('sidebarThreadDelete')}</span>
      </button>

      <div className="my-1 h-px bg-ds-border-muted" />

      <ContextMenuColorBar
        value={labelColor}
        onChange={onLabelColorChange}
        clearLabel={t('threadMenuClearLabelColor')}
      />
    </div>
  )

  if (typeof document === 'undefined') return null
  return createPortal(menu, document.body)
}

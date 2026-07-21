import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactElement } from 'react'
import { createPortal } from 'react-dom'
import {
  Columns2,
  Copy,
  ExternalLink,
  FolderOpen,
  Pencil,
  X
} from 'lucide-react'
import { usePreferredEditorLabel } from '../../hooks/use-preferred-editor-label'

export type WorkspaceFileContextMenuAction =
  | 'open-with-editor'
  | 'edit'
  | 'split-right'
  | 'close'
  | 'reveal-in-folder'
  | 'copy-path'
  | 'copy-relative-path'
  | 'close-split'

type WorkspaceFileContextMenuProps = {
  x: number
  y: number
  canEdit: boolean
  canClose: boolean
  canSplitRight: boolean
  canCloseSplit: boolean
  onAction: (action: WorkspaceFileContextMenuAction) => void
  onClose: () => void
  t: (k: string, opts?: Record<string, unknown>) => string
}

const MENU_WIDTH = 240

export function WorkspaceFileContextMenu({
  x,
  y,
  canEdit,
  canClose,
  canSplitRight,
  canCloseSplit,
  onAction,
  onClose,
  t
}: WorkspaceFileContextMenuProps): ReactElement | null {
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
    const scale =
      parseFloat(
        getComputedStyle(document.documentElement).getPropertyValue('--ds-ui-scale')
      ) || 1
    const rectW = el.offsetWidth
    const rectH = el.offsetHeight
    const ax = x / scale
    const ay = y / scale
    const viewW = window.innerWidth / scale
    const viewH = window.innerHeight / scale
    const left = Math.max(8, Math.min(ax, viewW - rectW - 8))
    const top = Math.max(8, Math.min(ay, viewH - rectH - 8))
    setStyle({ position: 'fixed', left, top, width: MENU_WIDTH, zIndex: 130 })
  }, [x, y, editorLabel])

  useEffect(() => {
    const onPointerDown = (event: PointerEvent): void => {
      const target = event.target
      if (target instanceof Node && menuRef.current?.contains(target)) return
      onClose()
    }
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    const timer = window.setTimeout(() => {
      window.addEventListener('pointerdown', onPointerDown, true)
    }, 0)
    window.addEventListener('keydown', onKeyDown, true)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('pointerdown', onPointerDown, true)
      window.removeEventListener('keydown', onKeyDown, true)
    }
  }, [onClose])

  const run = (action: WorkspaceFileContextMenuAction): void => {
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
      <button type="button" className={itemClass} onClick={() => run('open-with-editor')}>
        <ExternalLink className={iconClass} strokeWidth={1.8} />
        <span className="min-w-0 truncate">
          {t('workspaceEditorOpenExternal', { editor: editorLabel })}
        </span>
      </button>
      <button
        type="button"
        className={itemClass}
        onClick={() => run('edit')}
        disabled={!canEdit}
      >
        <Pencil className={iconClass} strokeWidth={1.8} />
        <span className="min-w-0 truncate">{t('workspaceEditorEdit')}</span>
      </button>

      <div className="my-1 h-px bg-ds-border-muted" />

      <button
        type="button"
        className={itemClass}
        onClick={() => run('split-right')}
        disabled={!canSplitRight}
      >
        <Columns2 className={iconClass} strokeWidth={1.8} />
        <span className="min-w-0 truncate">{t('workspaceEditorSplitRight')}</span>
      </button>
      {canCloseSplit ? (
        <button type="button" className={itemClass} onClick={() => run('close-split')}>
          <Columns2 className={iconClass} strokeWidth={1.8} />
          <span className="min-w-0 truncate">{t('workspaceEditorCloseSplit')}</span>
        </button>
      ) : null}
      <button
        type="button"
        className={itemClass}
        onClick={() => run('close')}
        disabled={!canClose}
      >
        <X className={iconClass} strokeWidth={1.8} />
        <span className="min-w-0 truncate">{t('workspaceEditorCloseTab')}</span>
      </button>

      <div className="my-1 h-px bg-ds-border-muted" />

      <button type="button" className={itemClass} onClick={() => run('reveal-in-folder')}>
        <FolderOpen className={iconClass} strokeWidth={1.8} />
        <span className="min-w-0 truncate">{t('threadMenuRevealInFolder')}</span>
      </button>
      <button type="button" className={itemClass} onClick={() => run('copy-path')}>
        <Copy className={iconClass} strokeWidth={1.8} />
        <span className="min-w-0 truncate">{t('threadMenuCopyPath')}</span>
      </button>
      <button type="button" className={itemClass} onClick={() => run('copy-relative-path')}>
        <Copy className={iconClass} strokeWidth={1.8} />
        <span className="min-w-0 truncate">{t('threadMenuCopyRelativePath')}</span>
      </button>
    </div>
  )

  if (typeof document === 'undefined') return null
  return createPortal(menu, document.body)
}

import type { ReactElement } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { EditorInfo } from '@shared/editor'
import {
  Check,
  ChevronDown,
  Code2,
  FileEdit,
  FolderOpen,
  Globe2,
  Terminal
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { readPreferredEditorId, writePreferredEditorId } from '../../lib/editor-preferences'

export type RightPanelMode = 'changes' | 'browser' | 'file' | null

type Props = {
  rightPanelMode: RightPanelMode
  onToggleRightPanelMode: (mode: Exclude<RightPanelMode, null>) => void
  terminalPanelOpen: boolean
  terminalPanelEnabled: boolean
  onToggleTerminalPanel: () => void
}

export function WorkbenchTopBar({
  rightPanelMode,
  onToggleRightPanelMode,
  terminalPanelOpen,
  terminalPanelEnabled,
  onToggleTerminalPanel
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const [editors, setEditors] = useState<EditorInfo[]>([])
  const [selectedEditorId, setSelectedEditorId] = useState(() => readPreferredEditorId() ?? '')
  const [editorMenuOpen, setEditorMenuOpen] = useState(false)
  const [failedIconIds, setFailedIconIds] = useState<Set<string>>(() => new Set())
  const editorMenuRef = useRef<HTMLDivElement>(null)
  const items = [
    { mode: 'changes' as const, label: t('rightPanelChanges'), icon: FileEdit },
    { mode: 'browser' as const, label: t('rightPanelBrowser'), icon: Globe2 }
  ]
  const selectedEditor = useMemo(
    () => editors.find((editor) => editor.id === selectedEditorId) ?? editors[0],
    [editors, selectedEditorId]
  )

  useEffect(() => {
    let cancelled = false
    if (typeof window.dsGui?.listEditors !== 'function') return

    void window.dsGui.listEditors().then((result) => {
      if (cancelled) return
      const available = result.editors.filter((editor) => editor.available)
      const stored = readPreferredEditorId()
      const nextId =
        stored && available.some((editor) => editor.id === stored)
          ? stored
          : result.defaultEditorId
      setEditors(available)
      setSelectedEditorId(nextId)
      writePreferredEditorId(nextId)
    })

    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!editorMenuOpen) return
    const onPointerDown = (event: PointerEvent): void => {
      const target = event.target
      if (target instanceof Node && editorMenuRef.current?.contains(target)) return
      setEditorMenuOpen(false)
    }
    window.addEventListener('pointerdown', onPointerDown)
    return () => window.removeEventListener('pointerdown', onPointerDown)
  }, [editorMenuOpen])

  const chooseEditor = (editor: EditorInfo): void => {
    setSelectedEditorId(editor.id)
    writePreferredEditorId(editor.id)
    setEditorMenuOpen(false)
  }

  const markEditorIconFailed = (editorId: string): void => {
    setFailedIconIds((prev) => {
      if (prev.has(editorId)) return prev
      const next = new Set(prev)
      next.add(editorId)
      return next
    })
  }

  const renderEditorIcon = (editor: EditorInfo | null | undefined, className: string): ReactElement => {
    const Icon =
      editor?.kind === 'terminal' ? Terminal : editor?.kind === 'viewer' ? FolderOpen : Code2

    if (editor?.iconDataUrl && !failedIconIds.has(editor.id)) {
      return (
        <img
          src={editor.iconDataUrl}
          alt=""
          aria-hidden="true"
          className={`${className} shrink-0 rounded-[4px] object-contain`}
          onError={() => markEditorIconFailed(editor.id)}
        />
      )
    }

    return <Icon className={`${className} shrink-0`} strokeWidth={1.8} />
  }

  const toolButtonBase =
    'inline-flex h-6 shrink-0 items-center justify-center rounded-full border shadow-[inset_0_1px_0_rgba(255,255,255,0.45)] transition dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]'
  const toolButtonIdle =
    'border-transparent bg-ds-elevated/45 text-ds-faint opacity-90 hover:border-ds-border-muted hover:bg-ds-elevated/70 hover:text-ds-ink hover:opacity-100 dark:bg-white/4 dark:hover:bg-white/8'
  const toolButtonActive =
    'border-ds-border-strong bg-ds-elevated/80 text-ds-ink dark:bg-white/10'

  return (
    <div className="ds-no-drag flex shrink-0 items-center justify-end gap-1">
      <div ref={editorMenuRef} className="relative">
        <button
          type="button"
          onClick={() => setEditorMenuOpen((value) => !value)}
          className={`${toolButtonBase} ${toolButtonIdle} gap-1 px-2`}
          aria-label={t('editorPickerTitle')}
          aria-expanded={editorMenuOpen}
          title={
            selectedEditor
              ? t('editorPickerTitleWithEditor', { editor: selectedEditor.label })
              : t('editorPickerTitle')
          }
        >
          {renderEditorIcon(selectedEditor, 'h-3.5 w-3.5')}
          <ChevronDown className="h-2.5 w-2.5 opacity-60" strokeWidth={1.9} />
        </button>

        {editorMenuOpen ? (
          <div className="ds-card-strong absolute right-0 top-full z-50 mt-2 w-64 overflow-hidden rounded-[18px] border border-ds-border py-1.5 shadow-[0_18px_52px_rgba(15,23,42,0.18)] backdrop-blur-xl dark:shadow-[0_22px_58px_rgba(0,0,0,0.38)]">
            <div className="border-b border-ds-border-muted px-3 pb-2 pt-1.5 text-[11px] font-semibold text-ds-faint">
              {t('editorPickerMenuTitle')}
            </div>
            {editors.map((editor) => {
              const active = editor.id === selectedEditor?.id
              return (
                <button
                  key={editor.id}
                  type="button"
                  onClick={() => chooseEditor(editor)}
                  className={`flex w-full items-center gap-3 px-3 py-2.5 text-left text-[14px] transition ${
                    active
                      ? 'bg-ds-hover text-ds-ink'
                      : 'text-ds-muted hover:bg-ds-hover/70 hover:text-ds-ink'
                  }`}
                >
                  {renderEditorIcon(editor, 'h-4 w-4')}
                  <span className="min-w-0 flex-1 truncate">{editor.label}</span>
                  {active ? <Check className="h-4 w-4 shrink-0 text-accent" strokeWidth={2} /> : null}
                </button>
              )
            })}
          </div>
        ) : null}
      </div>

      <button
        type="button"
        onClick={onToggleTerminalPanel}
        disabled={!terminalPanelEnabled}
        className={`${toolButtonBase} w-6 disabled:cursor-not-allowed disabled:opacity-45 ${
          terminalPanelOpen ? toolButtonActive : toolButtonIdle
        }`}
        aria-label={terminalPanelEnabled ? t('terminalToggle') : t('terminalWorkspaceRequired')}
        aria-pressed={terminalPanelOpen}
        title={terminalPanelEnabled ? t('terminalToggle') : t('terminalWorkspaceRequired')}
      >
        <Terminal className="h-3.5 w-3.5" strokeWidth={1.75} />
      </button>

      {items.map((item) => {
        const active = rightPanelMode === item.mode
        const Icon = item.icon
        return (
          <button
            key={item.mode}
            type="button"
            onClick={() => onToggleRightPanelMode(item.mode)}
            className={`${toolButtonBase} w-6 ${active ? toolButtonActive : toolButtonIdle}`}
            aria-label={item.label}
            aria-pressed={active}
            title={item.label}
          >
            <Icon className="h-3.5 w-3.5" strokeWidth={1.75} />
          </button>
        )
      })}
    </div>
  )
}

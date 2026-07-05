import type { ReactElement } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { EditorInfo } from '@shared/editor'
import { Check, ChevronDown, Code2, FolderOpen, Terminal } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { readPreferredEditorId, writePreferredEditorId } from '../lib/editor-preferences'

function renderEditorIcon(
  editor: EditorInfo | null | undefined,
  className: string,
  failedIconIds: Set<string>,
  onIconFailed: (editorId: string) => void
): ReactElement {
  const Icon =
    editor?.kind === 'terminal' ? Terminal : editor?.kind === 'viewer' ? FolderOpen : Code2

  if (editor?.iconDataUrl && !failedIconIds.has(editor.id)) {
    return (
      <img
        src={editor.iconDataUrl}
        alt=""
        aria-hidden="true"
        className={`${className} shrink-0 rounded-[4px] object-contain`}
        onError={() => onIconFailed(editor.id)}
      />
    )
  }

  return <Icon className={`${className} shrink-0`} strokeWidth={1.8} />
}

export function DefaultEditorPicker(): ReactElement {
  const { t } = useTranslation('common')
  const [editors, setEditors] = useState<EditorInfo[]>([])
  const [selectedEditorId, setSelectedEditorId] = useState(() => readPreferredEditorId() ?? '')
  const [editorMenuOpen, setEditorMenuOpen] = useState(false)
  const [failedIconIds, setFailedIconIds] = useState<Set<string>>(() => new Set())
  const editorMenuRef = useRef<HTMLDivElement>(null)

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

  return (
    <div ref={editorMenuRef} className="relative">
      <button
        type="button"
        onClick={() => setEditorMenuOpen((value) => !value)}
        disabled={editors.length === 0}
        className="ds-no-drag inline-flex h-8 shrink-0 items-center justify-center gap-1 rounded-full border border-transparent bg-ds-elevated/45 px-2 text-ds-faint shadow-[inset_0_1px_0_rgba(255,255,255,0.45)] transition hover:border-ds-border-muted hover:bg-ds-elevated/70 hover:text-ds-ink disabled:cursor-not-allowed disabled:opacity-45 dark:bg-white/4 dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]"
        aria-label={t('editorPickerTitle')}
        aria-expanded={editorMenuOpen}
        title={
          selectedEditor
            ? t('editorPickerTitleWithEditor', { editor: selectedEditor.label })
            : t('editorPickerTitle')
        }
      >
        {renderEditorIcon(selectedEditor, 'h-4 w-4', failedIconIds, markEditorIconFailed)}
        <ChevronDown className="h-3 w-3 opacity-60" strokeWidth={1.9} />
      </button>

      {editorMenuOpen ? (
        <div className="absolute right-0 top-full z-50 mt-2 w-64 overflow-hidden rounded-[12px] border border-ds-border bg-ds-elevated py-1.5 shadow-[0_18px_52px_rgba(15,23,42,0.18)] dark:shadow-[0_22px_58px_rgba(0,0,0,0.38)]">
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
                {renderEditorIcon(editor, 'h-4 w-4', failedIconIds, markEditorIconFailed)}
                <span className="min-w-0 flex-1 truncate">{editor.label}</span>
                {active ? <Check className="h-4 w-4 shrink-0 text-accent" strokeWidth={2} /> : null}
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}

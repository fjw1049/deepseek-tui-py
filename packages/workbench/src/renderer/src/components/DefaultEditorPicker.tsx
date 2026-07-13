import type { ReactElement } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { EditorInfo } from '@shared/editor'
import { Check, ChevronDown, Code2, FolderOpen, Terminal } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { readPreferredEditorId, writePreferredEditorId } from '../lib/editor-preferences'

function renderEditorIcon(
  editor: EditorInfo | null | undefined,
  failedIconIds: Set<string>,
  onIconFailed: (editorId: string) => void,
  sizeClass = 'h-5 w-5'
): ReactElement {
  const Icon =
    editor?.kind === 'terminal' ? Terminal : editor?.kind === 'viewer' ? FolderOpen : Code2

  if (editor?.iconDataUrl && !failedIconIds.has(editor.id)) {
    return (
      <span className={`inline-flex ${sizeClass} shrink-0 items-center justify-center overflow-hidden rounded-[6px] bg-black/[0.04] ring-1 ring-black/[0.06] dark:bg-white/[0.08] dark:ring-white/[0.08]`}>
        <img
          src={editor.iconDataUrl}
          alt=""
          aria-hidden="true"
          className="h-full w-full object-contain"
          draggable={false}
          onError={() => onIconFailed(editor.id)}
        />
      </span>
    )
  }

  return (
    <span className={`inline-flex ${sizeClass} shrink-0 items-center justify-center rounded-[6px] bg-black/[0.04] text-ds-muted ring-1 ring-black/[0.06] dark:bg-white/[0.08] dark:ring-white/[0.08]`}>
      <Icon className="h-3.5 w-3.5" strokeWidth={1.8} />
    </span>
  )
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
      const available = result.editors.filter(
        (editor) => editor.available && editor.id !== 'system'
      )
      const stored = readPreferredEditorId()
      const storedOk = stored && stored !== 'system' && available.some((editor) => editor.id === stored)
      const nextId = storedOk
        ? stored
        : available.some((editor) => editor.id === result.defaultEditorId)
          ? result.defaultEditorId
          : available[0]?.id ?? ''
      setEditors(available)
      setSelectedEditorId(nextId)
      if (nextId) writePreferredEditorId(nextId)
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
        className="ds-no-drag inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-full border border-transparent bg-ds-elevated/55 px-2 text-ds-faint shadow-[inset_0_1px_0_rgba(255,255,255,0.5)] transition duration-100 ease-out hover:border-ds-border-muted hover:bg-ds-elevated/80 hover:text-ds-ink active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-45 dark:bg-white/[0.06] dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]"
        aria-label={t('editorPickerTitle')}
        aria-expanded={editorMenuOpen}
        title={
          selectedEditor
            ? t('editorPickerTitleWithEditor', { editor: selectedEditor.label })
            : t('editorPickerTitle')
        }
      >
        {renderEditorIcon(selectedEditor, failedIconIds, markEditorIconFailed, 'h-4 w-4')}
        <ChevronDown className="h-3 w-3 opacity-55" strokeWidth={1.9} />
      </button>

      {editorMenuOpen ? (
        <div className="absolute right-0 top-full z-50 mt-2 w-[280px] overflow-hidden rounded-[14px] border border-white/40 bg-ds-elevated/92 shadow-[0_18px_50px_rgba(15,23,42,0.16),0_1px_0_rgba(255,255,255,0.55)_inset] backdrop-blur-2xl dark:border-white/10 dark:bg-[#1c1c1e]/88 dark:shadow-[0_22px_56px_rgba(0,0,0,0.5),0_1px_0_rgba(255,255,255,0.06)_inset]">
          <div className="border-b border-black/[0.06] px-3.5 pb-2.5 pt-3 dark:border-white/[0.08]">
            <div className="text-[12px] font-semibold tracking-[-0.01em] text-ds-ink">
              {t('editorPickerMenuTitle')}
            </div>
            <div className="mt-1 text-[11px] leading-[1.35] text-ds-faint">
              {t('editorPickerMenuHint')}
            </div>
          </div>
          <div className="max-h-[320px] overflow-y-auto p-1.5">
            {editors.map((editor) => {
              const active = editor.id === selectedEditor?.id
              return (
                <button
                  key={editor.id}
                  type="button"
                  onClick={() => chooseEditor(editor)}
                  className={`flex w-full items-center gap-3 rounded-[10px] px-2.5 py-2 text-left transition duration-100 ease-out active:scale-[0.985] ${
                    active
                      ? 'bg-accent/12 text-ds-ink dark:bg-accent/20'
                      : 'text-ds-muted hover:bg-black/[0.04] hover:text-ds-ink dark:hover:bg-white/[0.06]'
                  }`}
                >
                  {renderEditorIcon(editor, failedIconIds, markEditorIconFailed, 'h-5 w-5')}
                  <span className="min-w-0 flex-1 truncate text-[13px] font-medium tracking-[-0.01em]">
                    {editor.label}
                  </span>
                  {active ? (
                    <Check className="h-4 w-4 shrink-0 text-accent" strokeWidth={2.2} />
                  ) : null}
                </button>
              )
            })}
          </div>
        </div>
      ) : null}
    </div>
  )
}

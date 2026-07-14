import type { ReactElement } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { EditorInfo } from '@shared/editor'
import { Check, ChevronDown, Code2, FolderOpen, Terminal } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { readPreferredEditorId, writePreferredEditorId } from '../lib/editor-preferences'

function EditorGlyph({
  editor,
  failedIconIds,
  onIconFailed,
  compact = false
}: {
  editor: EditorInfo | null | undefined
  failedIconIds: Set<string>
  onIconFailed: (editorId: string) => void
  compact?: boolean
}): ReactElement {
  const Icon =
    editor?.kind === 'terminal' ? Terminal : editor?.kind === 'viewer' ? FolderOpen : Code2
  const shellClass = compact
    ? 'inline-flex h-4 w-4 shrink-0 items-center justify-center overflow-hidden rounded-[5px] bg-black/[0.04] text-ds-muted ring-1 ring-black/[0.06] dark:bg-white/[0.08] dark:ring-white/[0.08]'
    : 'ds-editor-picker-menu__icon'

  if (editor?.iconDataUrl && !failedIconIds.has(editor.id)) {
    return (
      <span className={shellClass} aria-hidden>
        <img
          src={editor.iconDataUrl}
          alt=""
          aria-hidden="true"
          className={compact ? 'h-full w-full object-contain' : undefined}
          draggable={false}
          onError={() => onIconFailed(editor.id)}
        />
      </span>
    )
  }

  return (
    <span className={shellClass} aria-hidden>
      <Icon className="h-3.5 w-3.5" strokeWidth={1.85} />
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
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        setEditorMenuOpen(false)
      }
    }
    window.addEventListener('pointerdown', onPointerDown)
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('pointerdown', onPointerDown)
      window.removeEventListener('keydown', onKeyDown)
    }
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
        className="ds-editor-picker-trigger ds-no-drag"
        aria-label={t('editorPickerTitle')}
        aria-expanded={editorMenuOpen}
        aria-haspopup="menu"
        title={
          selectedEditor
            ? t('editorPickerTitleWithEditor', { editor: selectedEditor.label })
            : t('editorPickerTitle')
        }
      >
        <EditorGlyph
          editor={selectedEditor}
          failedIconIds={failedIconIds}
          onIconFailed={markEditorIconFailed}
          compact
        />
        <ChevronDown className="ds-editor-picker-trigger__chevron h-3 w-3" strokeWidth={1.9} />
      </button>

      {editorMenuOpen ? (
        <div
          className="ds-editor-picker-menu absolute right-0 top-full z-50 mt-2"
          role="menu"
          aria-label={t('editorPickerMenuTitle')}
        >
          <div className="ds-editor-picker-menu__header">
            <div className="ds-editor-picker-menu__title">{t('editorPickerMenuTitle')}</div>
            <div className="ds-editor-picker-menu__hint">{t('editorPickerMenuHint')}</div>
          </div>
          <div className="ds-editor-picker-menu__list">
            {editors.map((editor) => {
              const active = editor.id === selectedEditor?.id
              return (
                <button
                  key={editor.id}
                  type="button"
                  role="menuitemradio"
                  aria-checked={active}
                  onClick={() => chooseEditor(editor)}
                  className={`ds-editor-picker-menu__row ${
                    active ? 'ds-editor-picker-menu__row--active' : ''
                  }`}
                >
                  <EditorGlyph
                    editor={editor}
                    failedIconIds={failedIconIds}
                    onIconFailed={markEditorIconFailed}
                  />
                  <span className="ds-editor-picker-menu__row-title min-w-0 flex-1">
                    {editor.label}
                  </span>
                  <span className="ds-editor-picker-menu__check" aria-hidden>
                    {active ? <Check className="h-4 w-4" strokeWidth={2.2} /> : null}
                  </span>
                </button>
              )
            })}
          </div>
        </div>
      ) : null}
    </div>
  )
}

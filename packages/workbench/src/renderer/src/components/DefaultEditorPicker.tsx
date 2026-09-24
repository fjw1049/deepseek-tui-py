import type { ReactElement } from 'react'
import { useEffect, useState } from 'react'
import type { EditorInfo } from '@shared/editor'
import { Code2, FolderOpen, Terminal } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { SettingsSelect } from './settings/SettingsSelect'
import { readPreferredEditorId, writePreferredEditorId } from '../lib/editor-preferences'

export function DefaultEditorPicker(): ReactElement {
  const { t } = useTranslation('common')
  const [editors, setEditors] = useState<EditorInfo[]>([])
  const [selectedEditorId, setSelectedEditorId] = useState(() => readPreferredEditorId() ?? '')

  const [failedIconIds, setFailedIconIds] = useState<Set<string>>(() => new Set())

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

  return (
    <SettingsSelect
      value={selectedEditorId}
      disabled={editors.length === 0}
      aria-label={t('editorPickerTitle')}
      renderIcon={(value) => {
        const editor = editors.find((item) => item.id === value)
        const Icon = editor?.kind === 'terminal' ? Terminal : editor?.kind === 'viewer' ? FolderOpen : Code2
        return editor?.iconDataUrl && !failedIconIds.has(editor.id) ? (
          <img
            src={editor.iconDataUrl}
            alt=""
            aria-hidden
            draggable={false}
            className="h-4 w-4 shrink-0 object-contain"
            onError={() => setFailedIconIds((previous) => new Set(previous).add(editor.id))}
          />
        ) : (
          <Icon className="h-4 w-4 shrink-0 text-ds-muted" aria-hidden />
        )
      }}
      onChange={(event) => {
        setSelectedEditorId(event.target.value)
        writePreferredEditorId(event.target.value)
      }}
    >
      {editors.map((editor) => (
        <option key={editor.id} value={editor.id}>
          {editor.label}
        </option>
      ))}
    </SettingsSelect>
  )
}

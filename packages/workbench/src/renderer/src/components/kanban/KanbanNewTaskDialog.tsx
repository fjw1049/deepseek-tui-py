import { useEffect, useMemo, useState, type ReactElement } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'
import {
  filterComposerModelOptions,
  formatComposerModelLabel
} from '../../lib/composer-model-label'
import { useChatStore } from '../../store/chat-store'
import { CHATS_COLUMN_ID, type KanbanProjectBoard } from './kanban.logic'

export type KanbanNewTaskSubmit = {
  projectId: string
  workspacePath: string | null
  prompt: string
  model: string
  sendAsDraft: boolean
}

export function KanbanNewTaskDialog({
  open,
  projects,
  initialProjectId,
  initialSendAsDraft = false,
  submitting = false,
  onClose,
  onSubmit
}: {
  open: boolean
  projects: readonly Pick<KanbanProjectBoard, 'projectId' | 'projectName' | 'workspacePath'>[]
  initialProjectId: string | null
  initialSendAsDraft?: boolean
  submitting?: boolean
  onClose: () => void
  onSubmit: (input: KanbanNewTaskSubmit) => void | Promise<void>
}): ReactElement | null {
  const { t } = useTranslation('common')
  const composerModel = useChatStore((s) => s.composerModel)
  const composerPickList = useChatStore((s) => s.composerPickList)
  const composerModelMeta = useChatStore((s) => s.composerModelMeta)

  const options = useMemo(() => {
    const list = [...projects]
    if (!list.some((project) => project.projectId === CHATS_COLUMN_ID)) {
      list.push({
        projectId: CHATS_COLUMN_ID,
        projectName: t('kanbanChatsColumn'),
        workspacePath: null
      })
    }
    return list
  }, [projects, t])

  const modelOptions = useMemo(
    () => filterComposerModelOptions(composerModel, composerPickList),
    [composerModel, composerPickList]
  )

  const [projectId, setProjectId] = useState(initialProjectId ?? options[0]?.projectId ?? '')
  const [prompt, setPrompt] = useState('')
  const [model, setModel] = useState(composerModel.trim() || modelOptions[0] || '')
  const [sendAsDraft, setSendAsDraft] = useState(initialSendAsDraft)

  useEffect(() => {
    if (!open) return
    setProjectId(initialProjectId ?? options[0]?.projectId ?? '')
    setPrompt('')
    setModel(composerModel.trim() || modelOptions[0] || '')
    setSendAsDraft(initialSendAsDraft)
  }, [open, initialProjectId, initialSendAsDraft, options, composerModel, modelOptions])

  if (!open) return null

  const selected = options.find((project) => project.projectId === projectId) ?? options[0]
  const canSubmit =
    Boolean(selected) && prompt.trim().length > 0 && model.trim().length > 0 && !submitting

  const submit = (): void => {
    if (!selected || !canSubmit) return
    void onSubmit({
      projectId: selected.projectId,
      workspacePath: selected.workspacePath,
      prompt: prompt.trim(),
      model: model.trim(),
      sendAsDraft
    })
  }

  return createPortal(
    <div className="ds-no-drag fixed inset-0 z-[200] flex items-center justify-center bg-black/45 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('kanbanNewTask')}
        className="w-full max-w-lg rounded-2xl border border-ds-border bg-ds-elevated shadow-panel"
      >
        <div className="flex items-center justify-between gap-3 border-b border-ds-border px-4 py-3">
          <h2 className="text-[14px] font-semibold text-ds-ink">{t('kanbanNewTask')}</h2>
          <button
            type="button"
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-ds-faint hover:bg-ds-hover hover:text-ds-ink"
            onClick={onClose}
            aria-label={t('kanbanDialogClose')}
          >
            <X className="h-4 w-4" strokeWidth={1.9} />
          </button>
        </div>
        <div className="flex flex-col gap-3 px-4 py-3">
          <label className="flex flex-col gap-1.5 text-[12px] text-ds-muted">
            {t('kanbanTaskProject')}
            <select
              value={selected?.projectId ?? ''}
              onChange={(event) => setProjectId(event.target.value)}
              className="rounded-lg border border-ds-border bg-ds-card px-2.5 py-2 text-[13px] text-ds-ink outline-none focus:ring-1 focus:ring-sky-500/40"
            >
              {options.map((project) => (
                <option key={project.projectId} value={project.projectId}>
                  {project.projectName}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1.5 text-[12px] text-ds-muted">
            {t('kanbanTaskModel')}
            <select
              value={model}
              onChange={(event) => setModel(event.target.value)}
              className="rounded-lg border border-ds-border bg-ds-card px-2.5 py-2 text-[13px] text-ds-ink outline-none focus:ring-1 focus:ring-sky-500/40"
            >
              {modelOptions.map((id) => (
                <option key={id} value={id}>
                  {formatComposerModelLabel(id, composerModelMeta)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1.5 text-[12px] text-ds-muted">
            {t('kanbanTaskPrompt')}
            <textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              rows={6}
              placeholder={t('kanbanTaskPromptPlaceholder')}
              className="resize-y rounded-lg border border-ds-border bg-ds-card px-3 py-2 text-[13px] leading-5 text-ds-ink outline-none focus:ring-1 focus:ring-sky-500/40"
              autoFocus
            />
          </label>
          <label className="flex items-center gap-2 text-[12px] text-ds-muted">
            <input
              type="checkbox"
              checked={sendAsDraft}
              onChange={(event) => setSendAsDraft(event.target.checked)}
            />
            {t('kanbanSendAsDraft')}
          </label>
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-ds-border px-4 py-3">
          <button
            type="button"
            className="rounded-lg px-3 py-1.5 text-[12px] text-ds-muted hover:bg-ds-hover hover:text-ds-ink"
            onClick={onClose}
            disabled={submitting}
          >
            {t('kanbanDialogCancel')}
          </button>
          <button
            type="button"
            className="rounded-lg bg-sky-600 px-3 py-1.5 text-[12px] font-medium text-white transition hover:bg-sky-500 disabled:opacity-50"
            onClick={submit}
            disabled={!canSubmit}
          >
            {sendAsDraft ? t('kanbanSaveDraft') : t('kanbanSendTask')}
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}

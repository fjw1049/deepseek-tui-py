import i18n from '../i18n'

/** A user review is required only when the stored task exceeds the current session. */
export async function requestTaskResume(
  id: string,
  threadId?: string | null
): Promise<Record<string, unknown>> {
  const path = `/v1/tasks/${encodeURIComponent(id)}/resume`
  const context = threadId ? { thread_id: threadId } : {}
  async function post(confirmationKey?: string): Promise<Record<string, unknown>> {
    const body = { ...context, ...(confirmationKey ? { confirmation_key: confirmationKey } : {}) }
    const r = Object.keys(body).length
      ? await window.dsGui.runtimeRequest(path, 'POST', JSON.stringify(body))
      : await window.dsGui.runtimeRequest(path, 'POST')
    if (!r.ok) throw new Error(r.body?.trim() || `resume task failed (${r.status})`)
    return JSON.parse(r.body) as Record<string, unknown>
  }
  let raw = await post()
  if (raw.code === 'resume_confirmation_required') {
    const changes = Array.isArray(raw.permission_changes) ? raw.permission_changes : []
    const value = (v: unknown): string =>
      typeof v === 'boolean' ? i18n.t(v ? 'taskResume.allowed' : 'taskResume.disallowed') : String(v)
    const lines = changes.map((change: { field: string; current: unknown; target: unknown }) =>
      `${i18n.t(`taskResume.${change.field}`)}: ${value(change.current)} → ${value(change.target)}`
    )
    const scope = raw.resume_permissions as Record<string, unknown> | undefined
    const message = `${i18n.t('taskResume.review')}\n\n${i18n.t('taskResume.workspace')}: ${scope?.workspace ?? ''}\n${lines.join('\n')}\n\n${i18n.t('taskResume.confirm')}`
    if (!window.confirm(message)) throw new Error(i18n.t('taskResume.cancelled'))
    if (typeof raw.confirmation_key !== 'string') throw new Error('Missing resume review')
    raw = await post(raw.confirmation_key)
    // Never reuse consent after permissions change while the dialog is open.
    if (raw.code === 'resume_confirmation_required') throw new Error(i18n.t('taskResume.changed'))
  }
  if (raw.ok === false) throw new Error(typeof raw.error === 'string' ? raw.error : 'resume task failed')
  return raw
}

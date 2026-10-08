import { useEffect, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { browserRequest } from './BrowserWorkspace'

type Workflow = { id: string; steps: number; status: string }
type Preview = { inputs: { name: string }[]; steps: { id: string; kind: string; description: string }[] }
type Installation = { status: string; logs: string[]; error: string | null }

export function BrowserSessionSettings({ threadId, active, userControls, recording }: {
  threadId: string; active: boolean; userControls: boolean; recording: boolean
}): ReactElement {
  const { t } = useTranslation('common')
  const [persistent, setPersistent] = useState(false)
  const [environment, setEnvironment] = useState('')
  const [items, setItems] = useState<Workflow[]>([])
  const [selected, setSelected] = useState('')
  const [preview, setPreview] = useState<Preview | null>(null)
  const [inputs, setInputs] = useState<Record<string, string>>({})
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [installation, setInstallation] = useState<Installation | null>(null)
  const [skillName, setSkillName] = useState('')
  const [skillDescription, setSkillDescription] = useState('')
  const [skill, setSkill] = useState<{ content: string; digest: string } | null>(null)
  const [installedPath, setInstalledPath] = useState('')
  const button = 'rounded border border-ds-border px-2 py-1.5 text-xs disabled:opacity-40'

  useEffect(() => {
    let disposed = false
    void Promise.all([
      browserRequest<{ persistent: boolean }>(threadId, '/preferences'),
      browserRequest<{ items: Workflow[] }>(threadId, '/workflows')
    ]).then(([prefs, flows]) => {
      if (!disposed) { setPersistent(prefs.persistent); setItems(flows.items ?? []) }
    }).catch((e: Error) => { if (!disposed) setError(e.message) })
    return () => { disposed = true }
  }, [threadId, recording])

  useEffect(() => {
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async (): Promise<void> => {
      try {
        const result = await browserRequest<Installation>(threadId, '/installation')
        if (disposed) return
        setInstallation(result)
        if (result.status === 'running') timer = setTimeout(() => void poll(), 1000)
      } catch (e) { if (!disposed) setError(String(e)) }
    }
    void poll()
    return () => { disposed = true; clearTimeout(timer) }
  }, [threadId, installation?.status])

  async function perform(work: () => Promise<void>): Promise<void> {
    setBusy(true); setError('')
    try { await work() } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }

  return <details className="mb-3 border-b border-ds-border pb-2 text-xs">
    <summary className="cursor-pointer py-2">{t('browserSessionSettings')}</summary>
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <button className={button} disabled={busy} onClick={() => void perform(async () => {
          const result = await browserRequest<{ ready: boolean; message: string; python: string }>(threadId, '/environment')
          setEnvironment(`${result.ready ? t('browserEnvironmentReady') : result.message} · Python ${result.python}`)
        })}>{t('browserCheckEnvironment')}</button>
        <button className={button} disabled={busy} onClick={() => void perform(async () => {
          await browserRequest(threadId, '/recover', {})
        })}>{t('browserRecover')}</button>
      </div>
      {environment ? <p role="status">{environment}</p> : null}
      <button className={button} disabled={busy} onClick={() => void perform(async () => {
        setInstallation(await browserRequest<Installation>(threadId, '/installation', {
          action: installation?.status === 'running' ? 'stop' : 'start'
        }))
      })}>{t(installation?.status === 'running' ? 'browserInstallCancel' : 'browserInstall')}</button>
      <p className="text-ds-muted">{t('browserInstallHint')}</p>
      {installation && installation.status !== 'idle' ? <div role="status">
        {t(`browserInstallStatus_${installation.status}`)}
        {installation.error ? <p className="text-red-600">{installation.error}</p> : null}
        {installation.logs?.length ? <pre className="max-h-28 overflow-auto whitespace-pre-wrap">{installation.logs.join('\n')}</pre> : null}
      </div> : null}
      <label className="flex items-center gap-2"><input type="checkbox" checked={persistent} disabled={active || busy}
        onChange={(event) => { const value = event.target.checked; void perform(async () => {
          await browserRequest(threadId, '/preferences', { persistent: value }); setPersistent(value)
        }) }} />{t('browserPersistent')}</label>
      <p className="text-ds-muted">{t('browserPersistentHint')}</p>
      <button className={button} disabled={active || busy} onClick={() => {
        if (window.confirm(t('browserClearProfileConfirm'))) void perform(async () => {
          await browserRequest(threadId, '/clear-profile', {})
        })
      }}>{t('browserClearProfile')}</button>
      <div className="flex flex-wrap gap-2">
        <button className={button} disabled={busy || !userControls || !active} onClick={() => void perform(async () => {
          await browserRequest(threadId, '/workflows', { action: recording ? 'stop' : 'start' })
          const flows = await browserRequest<{ items: Workflow[] }>(threadId, '/workflows')
          setItems(flows.items)
        })}>{recording ? t('browserWorkflowStop') : t('browserWorkflowStart')}</button>
      </div>
      <p className="text-ds-muted">{t('browserWorkflowHint')}</p>
      {items.map((item) => <button key={item.id} className={`${button} mr-2`} disabled={busy || item.steps === 0}
        onClick={() => void perform(async () => {
          const result = await browserRequest<Preview>(threadId, '/workflows', { action: 'preview', recording_id: item.id })
          setSelected(item.id); setPreview(result); setInputs({}); setSkill(null); setInstalledPath('')
        })}>{item.id} · {item.steps}</button>)}
      {preview ? <div className="space-y-2 rounded border border-ds-border p-2">
        <ol className="max-h-40 overflow-auto">{preview.steps.map((step) => <li key={step.id}>{step.id}. {step.description || step.kind}</li>)}</ol>
        {preview.inputs.map((input) => <label key={input.name} className="block">{input.name}
          <input className="mt-1 w-full rounded border border-ds-border bg-transparent p-2" type="password" autoComplete="off"
            value={inputs[input.name] ?? ''} onChange={(event) => setInputs({ ...inputs, [input.name]: event.target.value })} />
        </label>)}
        <p className="text-ds-muted">{t('browserReplayHint')}</p>
        <button className={button} disabled={busy || !userControls || recording || preview.inputs.some((input) => !(input.name in inputs))}
          onClick={() => void perform(async () => {
            await browserRequest(threadId, '/workflows', { action: 'replay', recording_id: selected, inputs }); setInputs({})
          })}>{t('browserWorkflowReplay')}</button>
        <div className="space-y-2 border-t border-ds-border pt-2">
          <input aria-label={t('browserSkillName')} placeholder={t('browserSkillName')} className="w-full rounded border border-ds-border bg-transparent p-2"
            value={skillName} onChange={(event) => { setSkillName(event.target.value); setSkill(null); setInstalledPath('') }} />
          <input aria-label={t('browserSkillDescription')} placeholder={t('browserSkillDescription')} className="w-full rounded border border-ds-border bg-transparent p-2"
            value={skillDescription} onChange={(event) => { setSkillDescription(event.target.value); setSkill(null); setInstalledPath('') }} />
          <button className={button} disabled={busy || !skillName.trim() || !skillDescription.trim()} onClick={() => void perform(async () => {
            setSkill(await browserRequest(threadId, '/skills', { action: 'preview', recording_id: selected, name: skillName, description: skillDescription }))
            setInstalledPath('')
          })}>{t('browserSkillGenerate')}</button>
          {skill ? <>
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-ds-surface p-2">{skill.content}</pre>
            <p className="text-ds-muted">{t('browserSkillInstallHint')}</p>
            <button className={button} disabled={busy || !!installedPath} onClick={() => void perform(async () => {
              const result = await browserRequest<{ path: string }>(threadId, '/skills', {
                action: 'install', recording_id: selected, name: skillName, description: skillDescription, digest: skill.digest
              })
              setInstalledPath(result.path)
            })}>{t('browserSkillInstall')}</button>
          </> : null}
          {installedPath ? <p role="status">{t('browserSkillInstalled')} {installedPath}</p> : null}
        </div>
      </div> : null}
      {error ? <p role="alert" className="text-red-600">{error}</p> : null}
    </div>
  </details>
}

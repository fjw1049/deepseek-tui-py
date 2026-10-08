import { useEffect, useState, type ComponentProps, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Camera, CircleStop, Globe2, Play, Hand, Bot, RefreshCw } from 'lucide-react'
import { DevBrowserPanel } from './DevBrowserPanel'
import { BrowserSessionSettings } from './BrowserSessionSettings'
import { useChatStore } from '../store/chat-store'
import { formatAutomationApiError } from '../lib/automation-runtime-client'

type BrowserState = {
  active: boolean
  owner: 'agent' | 'user' | 'stopped'
  recording: boolean
  demo_status: string
  activity?: string
  workflow_recording?: boolean
  demo_step?: number
  demo_total?: number
  error: string | null
  log: { action: string; success: boolean }[]
  artifacts: { id: string; label: string; path: string }[]
}

export async function browserRequest<T>(threadId: string, suffix = '', body?: unknown): Promise<T> {
  const response = await window.dsGui.runtimeRequest(
    `/v1/threads/${encodeURIComponent(threadId)}/browser${suffix}`,
    body === undefined ? 'GET' : 'POST',
    body === undefined ? undefined : JSON.stringify(body)
  )
  if (!response.ok) throw new Error(formatAutomationApiError(response.body, `HTTP ${response.status}`))
  return JSON.parse(response.body) as T
}

export function BrowserWorkspace(props: ComponentProps<typeof DevBrowserPanel>): ReactElement {
  const [mode, setMode] = useState<'preview' | 'agent'>('preview')
  const threadId = useChatStore((state) => state.activeThreadId)
  const { t } = useTranslation('common')
  return <div className="flex h-full min-h-0 flex-col">
    <div className="flex gap-2 border-b border-ds-border p-2 text-xs">
      <button className={mode === 'preview' ? 'font-semibold text-ds-ink' : 'text-ds-muted'} onClick={() => setMode('preview')}>{t('browserNormalPreview')}</button>
      <button className={mode === 'agent' ? 'font-semibold text-ds-ink' : 'text-ds-muted'} onClick={() => setMode('agent')}>{t('browserAgentWorkspace')}</button>
    </div>
    {mode === 'preview' ? <DevBrowserPanel {...props} /> :
      threadId ? <AgentBrowserPanel key={threadId} threadId={threadId} /> :
        <p className="p-5 text-sm text-ds-muted">{t('browserNeedThread')}</p>}
  </div>
}

export function AgentBrowserPanel({ threadId }: { threadId: string }): ReactElement {
  const { t } = useTranslation('common')
  const [state, setState] = useState<BrowserState | null>(null)
  const [image, setImage] = useState<string | null>(null)
  const [artifactImage, setArtifactImage] = useState<string | null>(null)
  const [url, setUrl] = useState('http://127.0.0.1:5173')
  const [selector, setSelector] = useState('')
  const [text, setText] = useState('')
  const [dom, setDom] = useState('')
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const userControls = state?.owner === 'user'

  useEffect(() => {
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async (): Promise<void> => {
      try {
        const next = await browserRequest<BrowserState>(threadId)
        if (disposed) return
        setState(next)
        if (next.active) {
          const frame = await browserRequest<{ image: string | null }>(threadId, '/frame')
          if (!disposed && frame.image) setImage(frame.image)
        } else setImage(null)
      } catch (e) {
        if (!disposed) setError(e instanceof Error ? e.message : String(e))
      } finally {
        if (!disposed) timer = setTimeout(() => void poll(), 600)
      }
    }
    void poll()
    return () => { disposed = true; clearTimeout(timer) }
  }, [threadId])

  async function perform(suffix: string, body: unknown): Promise<void> {
    setError('')
    setPending(true)
    try {
      const result = await browserRequest<{ success?: boolean; content?: unknown }>(threadId, suffix, body)
      if (result.success === false) throw new Error(String(result.content))
      if (result.content !== undefined) setDom(String(result.content))
      setState(await browserRequest<BrowserState>(threadId))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setPending(false)
    }
  }
  const action = (body: unknown): void => { void perform('/action', body) }
  const button = 'inline-flex items-center gap-1 rounded-md border border-ds-border px-2 py-1.5 text-xs disabled:opacity-40'
  return <div className="flex min-h-0 flex-1 flex-col overflow-auto p-3 text-ds-ink">
    <div className="mb-3 flex items-center justify-between gap-2">
      <div><div className="text-sm font-semibold">Octop × Workbench</div>
        <div className="mt-1 text-xs text-ds-muted">{t('browserAgentSubtitle')}</div></div>
      <span className="rounded-full bg-ds-surface px-2 py-1 text-xs">
        {state?.active ? (userControls ? t('browserUserControl') : t('browserAgentControl')) : t('browserIdle')}
      </span>
    </div>
    <div className="mb-2 flex flex-wrap gap-2">
      <button className={button} disabled={pending || state?.demo_status === 'running' || state?.workflow_recording || userControls}
        onClick={() => { setArtifactImage(null); void perform('/demo', {}) }}><Play size={13} />{t('browserRunDemo')}</button>
      <button className={button} disabled={!state?.active}
        onClick={() => void perform('/control', { owner: userControls ? 'agent' : 'user' })}>
        {userControls ? <Bot size={13} /> : <Hand size={13} />}{userControls ? t('browserReturnControl') : t('browserTakeControl')}</button>
      <button className={button} disabled={!state?.active}
        onClick={() => void perform('/control', { owner: 'stopped' })}><CircleStop size={13} />{t('browserEndSession')}</button>
    </div>
    <form className="mb-2 flex gap-2" onSubmit={(event) => { event.preventDefault(); action({ action: 'open', url }) }}>
      <input aria-label={t('browserAddressPlaceholder')} value={url} onChange={(e) => setUrl(e.target.value)}
        className="min-w-0 flex-1 rounded-md border border-ds-border bg-transparent px-2 py-1.5 text-xs" />
      <button className={button} disabled={pending || (!!state?.active && !userControls)}><Globe2 size={13} />{t('browserOpen')}</button>
    </form>
    {error || state?.error ? <p role="alert" className="mb-2 rounded-md bg-red-500/10 p-2 text-xs text-red-600">{error || state?.error}</p> : null}
    {state?.demo_status === 'passed' ? <p className="mb-2 rounded-md bg-emerald-500/10 p-2 text-xs text-emerald-700">{t(state.activity === 'replay' ? 'browserReplayPassed' : 'browserDemoPassed')}</p> : null}
    {state?.demo_status === 'running' ? <div role="status" className="mb-2 text-xs text-ds-muted">
      <p>{t(state.activity === 'replay' ? 'browserReplayRunning' : 'browserDemoRunning')} {state.demo_step ?? 0} / {state.demo_total ?? 9}</p>
      <progress className="mt-1 w-full" aria-label={t(state.activity === 'replay' ? 'browserReplayRunning' : 'browserDemoRunning')} value={state.demo_step ?? 0} max={state.demo_total ?? 9} />
    </div> : null}
    {state?.demo_status === 'stopped' || state?.demo_status === 'interrupted' ? <p role="status" className="mb-2 text-xs text-ds-muted">{t('browserDemoStopped')}</p> : null}
    <div className="overflow-hidden rounded-lg border border-ds-border bg-white">
      {image ? <img src={image} alt={t('browserLiveView')} tabIndex={userControls ? 0 : -1}
        className={userControls ? 'block w-full cursor-crosshair' : 'block w-full'}
        onClick={(event) => {
          if (!userControls || pending) return
          const rect = event.currentTarget.getBoundingClientRect()
          action({ action: 'click', x: Math.min(1199, Math.floor((event.clientX - rect.left) * 1200 / rect.width)),
            y: Math.min(759, Math.floor((event.clientY - rect.top) * 760 / rect.height)) })
          event.currentTarget.focus()
        }}
        onKeyDown={(event) => {
          if (!userControls || pending || event.metaKey || event.ctrlKey || event.altKey || event.key === 'Tab') return
          event.preventDefault()
          action({ action: 'press', key: event.key })
        }} /> :
        <div className="p-8 text-center text-sm text-slate-500">{t('browserDemoIntro')}</div>}
    </div>
    <div className="my-2 flex flex-wrap gap-2">
      <button className={button} disabled={!userControls || pending} onClick={() => action({ action: 'observe' })}><RefreshCw size={13} />{t('browserReadElements')}</button>
      <button className={button} disabled={!userControls || pending} onClick={() => action({ action: 'screenshot' })}><Camera size={13} />{t('browserSaveEvidence')}</button>
      <button className={button} disabled={!userControls || pending} onClick={() => action({ action: state?.recording ? 'record_stop' : 'record_start' })}>{state?.recording ? t('browserFinishRecording') : t('browserRecordSteps')}</button>
      <button className={button} disabled={!userControls || pending} onClick={() => action({ action: 'scroll', direction: 'down' })}>{t('browserScrollDown')}</button>
    </div>
    <details className="mb-3 text-xs">
      <summary className="cursor-pointer py-2">{t('browserElementActions')}</summary>
      <div className="flex flex-col gap-2">
        <input className="rounded border border-ds-border bg-transparent p-2" placeholder={t('browserElementTarget')} value={selector} onChange={(e) => setSelector(e.target.value)} />
        <input className="rounded border border-ds-border bg-transparent p-2" placeholder={t('browserElementValue')} value={text} onChange={(e) => setText(e.target.value)} />
        <div className="flex gap-2">
          <button className={button} disabled={!userControls || pending || !selector} onClick={() => action({ action: 'fill', selector, text })}>{t('browserFill')}</button>
          <button className={button} disabled={!userControls || pending || !text.trim()} onClick={() => action({ action: 'check_text', text, timeout_ms: 3000 })}>{t('browserCheckText')}</button>
        </div>
        {dom ? <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-ds-surface p-2">{dom}</pre> : null}
      </div>
    </details>
    <BrowserSessionSettings threadId={threadId} active={!!state?.active} userControls={!!userControls} recording={!!state?.workflow_recording} />
    <div className="text-xs font-semibold">{t('browserEvidence')}</div>
    <div className="my-2 flex flex-wrap gap-2">{state?.artifacts.map((artifact, index) =>
      <button key={artifact.id} className={button} onClick={() => {
        void browserRequest<{ image: string }>(threadId, '/artifacts/' + artifact.id)
          .then((result) => setArtifactImage(result.image)).catch((e: Error) => setError(e.message))
      }}>{index + 1}. {artifact.id.endsWith('.gif') ? t('browserStepAnimation') : artifact.label === '失败现场' ? t('browserFailureEvidence') : t('browserSaveEvidence')}</button>
    )}</div>
    {artifactImage ? <img className="mb-3 w-full rounded-lg border border-ds-border" src={artifactImage} alt={t('browserEvidence')} /> : null}
    <ol className="space-y-1 text-xs text-ds-muted">{state?.log.map((entry, i) =>
      <li key={i}>{entry.success ? '✓' : '✕'} {entry.action}</li>
    )}</ol>
    <p className="mt-3 text-[11px] leading-relaxed text-ds-muted">{t('browserDemoDisclaimer')}</p>
  </div>
}

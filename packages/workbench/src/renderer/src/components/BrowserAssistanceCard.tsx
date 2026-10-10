import { useRef, useState } from 'react'
import { Hand, Check, LoaderCircle, ChevronDown } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import './browser-assistance.css'

export type Assistance = { id: string; thread_id: string; reason: string; status: 'pending' | 'human' }

export function AssistanceCard({ request, onRespond, onReveal }: {
  request: Assistance
  onRespond: (choice: string, text?: string) => Promise<void>
  onReveal: () => void
}): React.ReactElement {
  const { t } = useTranslation('common')
  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const busy = useRef(false)
  async function respond(choice: string): Promise<void> {
    if (busy.current) return
    busy.current = true; setPending(true); setError('')
    try { await onRespond(choice, text); if (choice === 'takeover') onReveal() }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { busy.current = false; setPending(false) }
  }
  const primary = 'inline-flex items-center gap-1.5 rounded-xl bg-ds-ink px-3 py-1.5 text-[12px] font-medium text-ds-canvas transition active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50'
  const secondary = 'rounded-xl border border-ds-border bg-ds-card px-3 py-1.5 text-[12px] font-medium text-ds-ink transition hover:bg-ds-hover active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50'
  const quiet = 'rounded-xl px-3 py-1.5 text-[12px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:pointer-events-none disabled:opacity-50'
  return <section className="ds-assistance ds-approval-bubble w-full overflow-hidden rounded-2xl border border-ds-border bg-ds-subtle text-[13px] leading-5 text-ds-ink"
    data-state={pending ? 'submitting' : request.status} aria-busy={pending} aria-label={t('browserAssistTitle')}>
    <div className="flex items-start gap-3 px-4 pt-3.5">
      <span aria-hidden="true" className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-xl border border-ds-border bg-ds-card text-ds-muted">
        {pending ? <LoaderCircle size={16} className="animate-spin motion-reduce:animate-none" /> : <Hand size={16} />}
      </span>
      <div className="min-w-0 flex-1 pb-3.5">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-semibold tracking-[-0.02em] text-ds-ink">{t(request.status === 'human' ? 'browserAssistHuman' : 'browserAssistTitle')}</span>
          <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium ${request.status === 'human' || pending ? 'border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-400' : 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400'}`}>
            {t(pending ? 'browserWorking' : request.status === 'human' ? 'browserAssistUserControl' : 'browserAssistPaused')}
          </span>
        </div>
        <p id={`assist-reason-${request.id}`} className={`mt-1.5 whitespace-pre-wrap break-words text-[13px] leading-5 text-ds-muted ${!expanded && request.reason.length > 180 ? 'line-clamp-3' : ''}`}>{request.reason}</p>
        {request.reason.length > 180 ? <button type="button" className="mt-2 inline-flex items-center gap-1 rounded-md text-[12px] font-medium text-ds-muted hover:text-ds-ink" aria-expanded={expanded} aria-controls={`assist-reason-${request.id}`} onClick={() => setExpanded(!expanded)}>
          {t(expanded ? 'browserAssistLess' : 'browserAssistMore')}<ChevronDown size={14} aria-hidden="true" className={expanded ? 'rotate-180' : ''} />
        </button> : null}
        {error ? <p role="alert" className="mt-2 text-[12px] text-ds-danger">{error}</p> : null}
      </div>
    </div>
    {request.status === 'human' ? <div className="border-t border-ds-border px-4 py-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <button type="button" className={primary} disabled={pending} onClick={() => void respond('continue')}><Check size={14} />{t(pending ? 'browserAssistChecking' : 'browserAssistContinue')}</button>
        <button type="button" className={secondary} disabled={pending} onClick={onReveal}>{t('browserAssistShowPage')}</button>
      </div>
      <p className="mt-2 text-[12px] text-ds-muted">{t('browserAssistHumanHint')}</p>
    </div> : editing ? <form className="border-t border-ds-border px-4 py-3" onSubmit={e => { e.preventDefault(); if (text.trim()) void respond('information') }}>
      <label className="text-[12px] font-medium" htmlFor={`assist-${request.id}`}>{t('browserAssistInputLabel')}</label>
      <textarea id={`assist-${request.id}`} autoFocus value={text} maxLength={8000} required disabled={pending} onChange={e => setText(e.target.value)} placeholder={t('browserAssistPlaceholder')}
        className="mt-2 block min-h-20 w-full resize-y rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[13px] text-ds-ink focus:outline-accent" />
      <p className="mt-2 text-[12px] text-ds-muted">{t('browserAssistPrivate')}</p>
      <div className="mt-3 flex flex-wrap items-center gap-1.5"><button type="submit" className={primary} disabled={pending || !text.trim()}>{t('browserAssistSubmit')}</button><button type="button" className={quiet} disabled={pending} onClick={() => setEditing(false)}>{t('cancel')}</button></div>
    </form> : <div className="border-t border-ds-border px-4 py-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <button type="button" className={primary} disabled={pending} onClick={() => void respond('takeover')}>{t('browserAssistTakeover')}</button>
        <button type="button" className={secondary} disabled={pending} onClick={() => setEditing(true)}>{t('browserAssistInformation')}</button>
        <button type="button" className={quiet} disabled={pending} onClick={() => void respond('ignore')}>{t('browserAssistIgnore')}</button>
      </div>
      <p className="mt-2 text-[12px] text-ds-muted">{t('browserAssistWaiting')}</p>
    </div>}
  </section>
}

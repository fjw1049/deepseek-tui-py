import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, MousePointerClick, LoaderCircle, Square, TriangleAlert, X } from 'lucide-react'

export type DemoStep = { kind: string; description?: string; url?: string | null; target?: { name?: string; text?: string } | null; value?: string | null; key?: string | null }
/** A finished demonstration waiting for the user: check its steps, then add it to the chat. */
export type DemoReview = { id: string; count: number; message: string; open: boolean; steps?: DemoStep[] | null; stepsError?: boolean }
/** Why a demonstration could not start, or could not be saved. */
export type DemoFailure = { stage: 'start' | 'save'; message: string }

/** One recorded step in the user's words: what was clicked or typed where. */
export function describeDemoStep(step: DemoStep, t: (key: string, options?: Record<string, unknown>) => string): string {
  const label = (step.target?.name || step.target?.text || '').split('\n').map(line => line.trim()).find(Boolean)?.slice(0, 40)
  const value = step.value ?? ''
  const page = (() => { try { return step.url ? new URL(step.url).host : '' } catch { return step.url ?? '' } })()
  if (step.kind === 'open' || step.kind === 'navigate') return t('browserDemoStepOpen', { target: page })
  if (step.kind === 'new_tab') return t('browserDemoStepTab', { target: page })
  if (step.kind === 'press') return t('browserDemoStepPress', { target: step.key ?? value })
  if (!label) return step.kind === 'click' ? t('browserDemoStepUnnamed') : step.description ?? step.kind
  if (step.kind === 'click') return t('browserDemoStepClick', { target: label })
  if (step.kind === 'fill') return t('browserDemoStepFill', { target: label, value })
  if (step.kind === 'select') return t('browserDemoStepSelect', { target: label, value })
  if (step.kind === 'set_checked') return t(value === 'false' ? 'browserDemoStepUncheck' : 'browserDemoStepCheck', { target: label })
  if (step.kind === 'scroll_to') return t('browserDemoStepScroll', { target: label })
  return step.description ?? step.kind
}

/** The demonstration in the toolbar's activity card, in the same place and rhythm as screen recording. */
export function BrowserDemoActivity({ recording, finishing, elapsed, review, failure, canAct, onFinish, onAdd, onToggleSteps, onRetry, onDismiss }: {
  recording: boolean; finishing: boolean; elapsed: string
  review: DemoReview | null; failure: DemoFailure | null
  /** The user holds the page, so finishing or starting again can run now. */
  canAct: boolean
  onFinish: () => void; onAdd: () => void; onToggleSteps: () => void; onRetry: () => void; onDismiss: () => void
}): ReactElement | null {
  const { t } = useTranslation('common')
  const dismiss = (label: string): ReactElement => <button type="button" className="ds-annotation-toolbar__btn" aria-label={label} title={label} onClick={onDismiss}><X size={15} /></button>
  if (recording || finishing) return <div className="ds-browser-recording-activity is-demo" role="group" aria-label={t('browserDemoStart')}>
    <div className="ds-browser-recording-activity__copy">
      <strong role="status">{finishing ? <LoaderCircle size={14} className="ds-browser-control-spinner" /> : <span className="ds-browser-recording-dot" />}
        {t(finishing ? 'browserDemoFinishing' : 'browserDemoRecording')}
        {finishing ? null : <span className="ds-browser-recording-time" aria-hidden="true">{elapsed}</span>}
      </strong>
      <small>{t(finishing ? 'browserDemoFinishingHint' : 'browserDemoRecordingHint')}</small>
    </div>
    <button type="button" className="ds-annotation-toolbar__primary" disabled={!canAct || finishing} aria-busy={finishing} onClick={onFinish}>
      {finishing ? null : <Square size={12} fill="currentColor" />}{t(finishing ? 'browserDemoFinishingButton' : 'browserDemoFinish')}</button>
  </div>
  if (failure) return <div className="ds-browser-recording-activity is-demo is-failed" role="group" aria-label={t('browserDemoStart')}>
    <div className="ds-browser-recording-activity__copy">
      <strong role="alert"><TriangleAlert size={14} />{t(failure.stage === 'start' ? 'browserDemoStartFailed' : 'browserDemoSaveFailed')}</strong>
      <small>{failure.message}</small>
    </div>
    <button type="button" className="ds-annotation-toolbar__primary" disabled={!canAct} onClick={onRetry}>{t('browserDemoRetry')}</button>
    {dismiss(t('browserDemoDismiss'))}
  </div>
  if (!review) return null
  return <div className="ds-browser-recording-activity is-demo" role="group" aria-label={t('browserDemoStart')}>
    <div className="ds-browser-recording-activity__copy">
      <strong role="status"><MousePointerClick size={15} />{t('browserDemoReviewTitle', { count: review.count })}</strong>
      <small>{t('browserDemoReviewHint')}</small>
    </div>
    <button type="button" className="ds-annotation-toolbar__primary" onClick={onAdd}>{t('browserDemoReviewAdd')}</button>
    <button type="button" className="ds-annotation-toolbar__btn" aria-expanded={review.open} onClick={onToggleSteps}>
      {t(review.open ? 'browserDemoReviewHide' : 'browserDemoReviewShow')}<ChevronDown size={14} className={review.open ? 'is-open' : ''} aria-hidden="true" /></button>
    {dismiss(t('browserDemoReviewDismiss'))}
    {review.open ? <div className="ds-browser-demo-steps">
      {review.steps ? <ol>{review.steps.map((step, index) => <li key={index}>{describeDemoStep(step, t)}</li>)}</ol>
        : <p role={review.stepsError ? 'alert' : undefined}>{t(review.stepsError ? 'browserDemoStepsFailed' : 'browserDemoReviewLoading')}</p>}
    </div> : null}
  </div>
}

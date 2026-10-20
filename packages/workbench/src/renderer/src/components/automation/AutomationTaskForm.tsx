import './automation-task-form.css'
import { confirmAsync } from '../../lib/confirm-dialog'
import { reportActionError } from '../../store/feedback-store'
import { useEffect, useRef, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ArrowLeft,
  CalendarClock,
  CheckCircle2,
  Loader2,
  Play,
  Settings
} from 'lucide-react'
import {
  createAutomation,
  formatAutomationWhen,
  runAutomationNow,
  updateAutomation,
  type AutomationRecord
} from '../../lib/automation-runtime-client'
import {
  ALL_WEEKDAYS,
  buildCreateAutomationInput,
  buildAutomationSchedulePayload,
  restoreAutomationSchedule,
  type AutomationDeliveryMode,
  type AutomationScheduleKind,
  type WeekdayToken
} from '../../lib/automation-task-form-model'
import { loadChannelDeliveryState } from '../../lib/resolve-channel-delivery'
import { useChatStore } from '../../store/chat-store'
import { SettingsSelect } from '../settings/SettingsSelect'

type Props = {
  runtimeReady: boolean
  workspaceRoot: string
  onBackToChat: () => void
  onOpenAutomationSettings: () => void
  onOpenRuntimeSettings: () => void
  initialAutomation?: AutomationRecord | null
  onSaved?: (record: AutomationRecord) => void
}

const WEEKDAY_LABELS: Record<WeekdayToken, string> = {
  MON: 'automationWeekdayMo',
  TUE: 'automationWeekdayTu',
  WED: 'automationWeekdayWe',
  THU: 'automationWeekdayTh',
  FRI: 'automationWeekdayFr',
  SAT: 'automationWeekdaySa',
  SUN: 'automationWeekdaySu'
}

function defaultOnceAt(runAt?: string | null): string {
  const date = runAt ? new Date(runAt) : new Date(Date.now() + 60 * 60 * 1000)
  const offsetMs = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, -1)
}

function errorKey(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error)
  if (
    message === 'prompt_required' ||
    message === 'once_at_invalid' ||
    message === 'interval_invalid' ||
    message === 'time_of_day_invalid' ||
    message === 'weekdays_required' ||
    message === 'cron_required' ||
    message === 'cron_invalid'
  ) {
    return `common:automationError_${message}`
  }
  return message
}

export function AutomationTaskForm({
  runtimeReady,
  workspaceRoot,
  onBackToChat,
  onOpenAutomationSettings,
  onOpenRuntimeSettings,
  initialAutomation = null,
  onSaved
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const setRoute = useChatStore((s) => s.setRoute)
  const [name, setName] = useState(initialAutomation?.name ?? '')
  const [prompt, setPrompt] = useState(initialAutomation?.prompt ?? '')
  const [initialSchedule] = useState(() => restoreAutomationSchedule(initialAutomation?.schedule ?? null))
  const [scheduleKind, setScheduleKind] = useState<AutomationScheduleKind>(initialAutomation ? initialSchedule.kind : 'daily')
  const previousSimpleKind = useRef<AutomationScheduleKind>(initialSchedule.kind === 'custom' ? 'daily' : initialAutomation ? initialSchedule.kind : 'daily')
  const [initialOnceAt] = useState(() => defaultOnceAt(initialAutomation?.next_run_at ?? initialAutomation?.last_run_at))
  const [onceAt, setOnceAt] = useState(initialOnceAt)
  const [everyHours, setEveryHours] = useState(initialSchedule.everyHours)
  const [timeOfDay, setTimeOfDay] = useState(initialSchedule.timeOfDay)
  const [weekdays, setWeekdays] = useState<WeekdayToken[]>(initialSchedule.weekdays)
  const [customCron, setCustomCron] = useState(initialAutomation?.schedule ?? '')
  const [workspaceOverride, setWorkspaceOverride] = useState(initialAutomation ? initialAutomation.cwds?.[0] ?? '' : workspaceRoot)
  const initialDeliveryMode: AutomationDeliveryMode =
    initialAutomation?.delivery?.mode === 'feishu' ||
    initialAutomation?.delivery?.mode === 'email' ||
    initialAutomation?.delivery?.mode === 'wecom'
      ? initialAutomation.delivery.mode
      : 'none'
  const [deliveryMode, setDeliveryMode] = useState<AutomationDeliveryMode>(initialDeliveryMode)
  const deliveryTouched = useRef(Boolean(initialAutomation))
  const [deliveryTarget, setDeliveryTarget] = useState(initialAutomation?.delivery?.to ?? '')
  const [feishuDefault, setFeishuDefault] = useState('')
  const [emailDefault, setEmailDefault] = useState('')
  const [feishuChannelReady, setFeishuChannelReady] = useState(false)
  const [wecomChannelReady, setWecomChannelReady] = useState(false)
  const [emailChannelReady, setEmailChannelReady] = useState(false)
  const [status, setStatus] = useState(initialAutomation?.status ?? 'active')
  const [dirty, setDirty] = useState(false)
  const [channelsLoading, setChannelsLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [runningNow, setRunningNow] = useState(false)
  const [created, setCreated] = useState<AutomationRecord | null>(null)
  const [notice, setNotice] = useState<{ tone: 'success' | 'error'; message: string } | null>(null)

  const leave = async (action: () => void): Promise<void> => {
    if (!submitting && (!dirty || await confirmAsync(t('automationDiscardChanges')))) action()
  }

  useEffect(() => {
    if (!initialAutomation) setWorkspaceOverride((current) => current || workspaceRoot)
  }, [workspaceRoot, initialAutomation])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      const state = await loadChannelDeliveryState()
      if (cancelled) return
      setFeishuDefault(state.feishuDefault)
      setEmailDefault(state.emailDefault)
      setFeishuChannelReady(state.feishuChannelReady)
      setWecomChannelReady(state.wecomChannelReady)
      setEmailChannelReady(state.emailChannelReady)
      if (!deliveryTouched.current) {
        deliveryTouched.current = true
        if (state.feishuChannelReady) {
          setDeliveryMode('feishu')
          setDeliveryTarget(state.feishuDefault)
        } else if (state.wecomChannelReady) {
          setDeliveryMode('wecom')
        } else if (state.emailChannelReady) {
          setDeliveryMode('email')
          setDeliveryTarget(state.emailDefault)
        }
      }
    })().catch((error) => {
      if (!cancelled) reportActionError(error)
    }).finally(() => {
      if (!cancelled) setChannelsLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const toggleWeekday = (day: WeekdayToken): void => {
    setWeekdays((current) =>
      current.includes(day) ? current.filter((item) => item !== day) : [...current, day]
    )
  }

  const submit = async (): Promise<void> => {
    if (!runtimeReady || submitting || channelsLoading) return
    const deliveryChanged = !initialAutomation || deliveryMode !== initialDeliveryMode || deliveryTarget !== (initialAutomation.delivery?.to ?? '')
    if (deliveryChanged && deliveryMode === 'feishu' && !feishuChannelReady) {
      setNotice({ tone: 'error', message: t('automationDeliveryFeishuNotConfigured') })
      return
    }
    if (deliveryChanged && deliveryMode === 'wecom' && !wecomChannelReady) {
      setNotice({ tone: 'error', message: t('automationDeliveryWecomNotConfigured') })
      return
    }
    if (deliveryChanged && deliveryMode === 'email' && !emailChannelReady) {
      setNotice({ tone: 'error', message: t('automationDeliveryEmailNotConfigured') })
      return
    }
    if (scheduleKind === 'once' && (!initialAutomation || initialAutomation.schedule || onceAt !== initialOnceAt) && new Date(onceAt).getTime() <= Date.now()) {
      setNotice({ tone: 'error', message: t('automationError_once_at_future') })
      return
    }
    setSubmitting(true)
    setNotice(null)
    try {
      const input = buildCreateAutomationInput({
        name,
        prompt,
        workspaceRoot: workspaceOverride,
        schedule: {
          kind: scheduleKind,
          onceAt,
          everyHours,
          timeOfDay,
          weekdays,
          customCron
        },
        deliveryMode,
        deliveryTarget,
        channelDefaults: { feishu: feishuDefault, email: emailDefault },
        createPaused: status === 'paused'
      })
      const record = initialAutomation
        ? await updateAutomation(initialAutomation.id, {
            ...input,
            timezone: initialAutomation.timezone,
            run_at: !initialAutomation.schedule && scheduleKind === 'once' && onceAt === initialOnceAt
              ? undefined : input.run_at,
            status: status === initialAutomation.status ? undefined : input.status,
            cwds: workspaceOverride === (initialAutomation.cwds?.[0] ?? '') ? undefined : input.cwds,
            delivery: deliveryMode === initialDeliveryMode && deliveryTarget === (initialAutomation.delivery?.to ?? '')
              ? undefined
              : input.delivery ?? {}
          })
        : await createAutomation(input)
      setDirty(false)
      if (onSaved) {
        onSaved(record)
        return
      }
      setCreated(record)
      setNotice({ tone: 'success', message: t('automationCreateSuccess', { name: record.name }) })
    } catch (err) {
      const key = errorKey(err)
      if (key.startsWith('common:')) setNotice({ tone: 'error', message: t(key.slice('common:'.length)) })
      else reportActionError(key)
    } finally {
      setSubmitting(false)
    }
  }

  const runNow = async (): Promise<void> => {
    if (!created || runningNow) return
    setRunningNow(true)
    setNotice(null)
    try {
      const run = await runAutomationNow(created.id)
      setNotice({
        tone: 'success',
        message: t('automationRunStarted', { taskId: run.task_id ?? '-' })
      })
    } catch (err) {
      reportActionError(err)
    } finally {
      setRunningNow(false)
    }
  }

  return (
    <div className="ds-feature-page ds-automation-form ds-page-scroll ds-no-drag flex min-h-0 flex-1 overflow-y-auto px-5 py-6 md:px-10 lg:px-16">
      <div className="automation-editor mx-auto flex w-full max-w-3xl flex-col gap-5">
        <div className="automation-editor__header flex flex-wrap items-start justify-between gap-3">
          <div>
            <button
              type="button"
              disabled={submitting}
              onClick={() => leave(onBackToChat)}
              className="automation-editor__back inline-flex items-center gap-1.5 text-[12px] text-ds-muted transition hover:text-ds-ink"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              {t('automationBackToList')}
            </button>
            <h1 className="mt-3 text-[28px] font-semibold tracking-[-0.03em] text-ds-ink">
              {initialAutomation ? t('automationEditTitle') : t('automationTaskTitle')}
            </h1>
            <p className="mt-2 max-w-2xl text-[14px] leading-6 text-ds-muted">
              {initialAutomation ? t('automationEditSubtitle') : t('automationTaskSubtitle')}
            </p>
          </div>
          {!runtimeReady ? (
            <button
              type="button"
              onClick={onOpenRuntimeSettings}
              className="inline-flex items-center gap-2 rounded-xl border border-amber-300/70 bg-amber-50 px-3 py-2 text-[13px] font-semibold text-amber-950 transition hover:bg-amber-100 dark:border-amber-700/70 dark:bg-amber-950/30 dark:text-amber-100"
            >
              <Settings className="h-4 w-4" />
              {t('automationConnectRuntime')}
            </button>
          ) : null}
        </div>

        {created ? (
          <div className="rounded-[16px] border border-emerald-300/70 bg-emerald-50/80 p-5 text-emerald-900 shadow-sm dark:border-emerald-800/70 dark:bg-emerald-950/25 dark:text-emerald-100">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="flex min-w-0 gap-3">
                <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0" />
                <div className="min-w-0">
                  <div className="text-[15px] font-semibold">
                    {t('automationCreatedTitle', { name: created.name })}
                  </div>
                  <div className="mt-1 text-[13px] opacity-80">
                    {t('automationCreatedNextRun', {
                      time: formatAutomationWhen(created.next_run_at)
                    })}
                  </div>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={onOpenAutomationSettings}
                  className="rounded-xl border border-emerald-500/30 bg-white/70 px-3 py-2 text-[13px] font-semibold transition hover:bg-white dark:bg-emerald-950/30"
                >
                  {t('automationViewList')}
                </button>
                <button
                  type="button"
                  disabled={runningNow}
                  onClick={() => void runNow()}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-3 py-2 text-[13px] font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-60"
                >
                  {runningNow ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                  {t('automationRunNow')}
                </button>
              </div>
            </div>
          </div>
        ) : null}

        <div className="automation-editor__body" onChangeCapture={() => setDirty(true)}>
          <fieldset disabled={submitting} className="m-0 grid min-w-0 gap-6 border-0 p-0">
            <div className="grid gap-4 md:grid-cols-[1fr_160px]">
              <label className="grid gap-2">
                <span className="text-[13px] font-semibold text-ds-ink">{t('automationNameLabel')}</span>
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder={t('automationNamePlaceholder')}
                  className="rounded-2xl border border-ds-border bg-ds-main px-4 py-3 text-[14px] text-ds-ink outline-none transition placeholder:text-ds-faint focus:border-accent/60"
                />
              </label>
              <label className="grid gap-2">
                <span className="text-[13px] font-semibold text-ds-ink">{t(initialAutomation ? 'automationEditStatusLabel' : 'automationStatusLabel')}</span>
                <SettingsSelect
                  aria-label={t('automationEditStatusLabel')}
                  disabled={submitting}
                  value={status}
                  onChange={(event) => { setStatus(event.target.value); setDirty(true) }}
                  wrapperClassName="automation-editor__select h-10 rounded-lg"
                >
                  <option value="active">{t(initialAutomation ? 'automationEditStatusActive' : 'automationStatusActive')}</option>
                  {initialAutomation?.status === 'completed' ? <option value="completed">{t('automationEditStatusCompleted')}</option> : null}
                  <option value="paused">{t(initialAutomation ? 'automationEditStatusPaused' : 'automationStatusPaused')}</option>
                </SettingsSelect>
              </label>
            </div>

            <label className="grid gap-2">
              <span className="text-[13px] font-semibold text-ds-ink">{t('automationPromptLabel')}</span>
              <textarea
                spellCheck={false}
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder={t('automationPromptPlaceholder')}
                className="automation-editor__prompt min-h-[180px] resize-y rounded-2xl border border-ds-border bg-ds-main px-4 py-3 text-[14px] leading-6 text-ds-ink outline-none transition placeholder:text-ds-faint focus:border-accent/60"
              />
            </label>

            <div className="automation-editor__section">
              <div className="mb-3 flex items-center gap-2 text-[13px] font-semibold text-ds-ink">
                <CalendarClock className="h-4 w-4 text-accent" />
                {t('automationScheduleLabel')}
              </div>
              <div className="grid gap-3 md:grid-cols-[200px_1fr]">
                <label className="grid content-start gap-2">
                  <span className="text-[12px] font-medium text-ds-muted">{t('automationFrequency')}</span>
                  <SettingsSelect
                    aria-label={t('automationFrequency')}
                    disabled={submitting}
                    value={scheduleKind}
                    onChange={(event) => { setScheduleKind(event.target.value as AutomationScheduleKind); setDirty(true) }}
                    wrapperClassName="automation-editor__select h-10 rounded-lg"
                  >
                    <option value="daily">{t('automationScheduleDaily')}</option>
                    <option value="weekdays">{t('automationScheduleWeekdays')}</option>
                    <option value="weekly">{t('automationScheduleWeekly')}</option>
                    <option value="hourly">{t('automationScheduleHourly')}</option>
                    <option value="once">{t('automationScheduleOnce')}</option>
                    {scheduleKind === 'custom' ? <option value="custom">{t('automationScheduleCustom')}</option> : null}
                  </SettingsSelect>
                </label>
                <div className="grid content-start gap-2">
                  {scheduleKind !== 'custom' ? <span className="text-[12px] font-medium text-ds-muted">{t(scheduleKind === 'once' ? 'automationRunDate' : scheduleKind === 'hourly' ? 'automationInterval' : 'automationRunTime')}</span> : null}
                  {scheduleKind === 'once' ? (
                    <input
                      aria-label={t('automationScheduleOnce')}
                      type="datetime-local"
                      step="any"
                      value={onceAt}
                      onChange={(event) => setOnceAt(event.target.value)}
                      className="rounded-2xl border border-ds-border bg-ds-card px-4 py-3 text-[14px] text-ds-ink outline-none focus:border-accent/60"
                    />
                  ) : null}
                  {scheduleKind === 'hourly' ? (
                    <SettingsSelect
                      aria-label={t('automationScheduleHourly')}
                      disabled={submitting}
                      value={everyHours}
                      onChange={(event) => { setEveryHours(event.target.value); setDirty(true) }}
                      wrapperClassName="automation-editor__select h-10 rounded-lg"
                    >
                      {[1, 2, 3, 4, 6, 8, 12].map(hours => (
                        <option key={hours} value={String(hours)}>{t('automationEveryHours', { count: hours })}</option>
                      ))}
                    </SettingsSelect>
                  ) : null}
                  {scheduleKind === 'daily' || scheduleKind === 'weekdays' || scheduleKind === 'weekly' ? (
                    <input
                      aria-label={t('automationRunTime')}
                      type="time"
                      value={timeOfDay}
                      onChange={(event) => setTimeOfDay(event.target.value)}
                      className="rounded-2xl border border-ds-border bg-ds-card px-4 py-3 text-[14px] text-ds-ink outline-none focus:border-accent/60"
                    />
                  ) : null}
                  {scheduleKind === 'weekly' ? (
                    <div className="flex flex-wrap gap-2">
                      {ALL_WEEKDAYS.map((day) => (
                        <button
                          key={day}
                          type="button"
                          aria-pressed={weekdays.includes(day)}
                          onClick={() => { toggleWeekday(day); setDirty(true) }}
                          className={`rounded-full border px-3 py-1.5 text-[12px] font-semibold transition ${
                            weekdays.includes(day)
                              ? 'border-accent/30 bg-accent/10 text-accent'
                              : 'border-ds-border bg-ds-card text-ds-muted hover:bg-ds-hover'
                          }`}
                        >
                          {t(WEEKDAY_LABELS[day])}
                        </button>
                      ))}
                    </div>
                  ) : null}
                  {scheduleKind === 'weekdays' ? <p className="text-[12px] leading-5 text-ds-muted">{t('automationScheduleWeekdaysHint')}</p> : null}

                </div>
              </div>
              <div role="status" className="automation-editor__summary">
                {scheduleKind === 'daily' ? t('automationSummaryDaily', { time: timeOfDay })
                  : scheduleKind === 'weekdays' ? t('automationSummaryWeekdays', { time: timeOfDay })
                  : scheduleKind === 'weekly' ? (weekdays.length ? t('automationSummaryWeekly', { days: ALL_WEEKDAYS.filter(day => weekdays.includes(day)).map(day => t(WEEKDAY_LABELS[day])).join(t('automationWeekdaySeparator')), time: timeOfDay }) : t('automationError_weekdays_required'))
                  : scheduleKind === 'hourly' ? t('automationSummaryHourly', { count: Number(everyHours) })
                  : scheduleKind === 'once' ? t('automationSummaryOnce', { time: onceAt.replace('T', ' ').slice(0, 16) })
                  : t('automationSummaryAdvanced')}
                  <span className="automation-editor__timezone">{t('automationScheduleTimezone', {
                    timezone: scheduleKind === 'once' ? Intl.DateTimeFormat().resolvedOptions().timeZone : initialAutomation?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone
                  })}</span>
              </div>
              <details open={scheduleKind === 'custom' ? true : undefined} className="automation-editor__advanced">
                <summary className="cursor-pointer text-[12px] text-ds-muted">{t('automationAdvancedSchedule')}</summary>
                <label className="mt-3 flex items-center gap-2 text-[13px] text-ds-ink">
                  <input type="checkbox" checked={scheduleKind === 'custom'} onChange={(event) => {
                    if (event.target.checked) {
                      previousSimpleKind.current = scheduleKind
                      try {
                        const payload = buildAutomationSchedulePayload({ kind: scheduleKind, onceAt, everyHours, timeOfDay, weekdays, customCron })
                        setCustomCron(payload.schedule ?? customCron)
                      } catch { /* Keep the previous advanced rule when simple fields are incomplete. */ }
                    }
                    setScheduleKind(event.target.checked ? 'custom' : previousSimpleKind.current)
                    setDirty(true)
                  }} />
                  {t('automationUseAdvancedSchedule')}
                </label>
                {scheduleKind === 'custom' ? (
                  <label className="mt-3 grid gap-2">
                    <span className="text-[12px] text-ds-muted">{t('automationScheduleCustomHint')}</span>
                    <input aria-label={t('automationScheduleCustom')} value={customCron} onChange={(event) => setCustomCron(event.target.value)} placeholder="0 9 * * 1-5" className="w-full rounded-xl border border-ds-border bg-ds-main px-4 py-3 font-mono text-[13px] text-ds-ink outline-none focus:border-accent/60" />
                  </label>
                ) : null}
              </details>
            </div>

            <div className="automation-editor__section">
              <div className="mb-3 text-[13px] font-semibold text-ds-ink">{t('automationDeliveryLabel')}</div>
              <div className="grid gap-3 md:grid-cols-[200px_1fr]">
                <label className="grid gap-2">
                  <SettingsSelect
                    aria-label={t('automationDeliveryLabel')}
                    disabled={submitting || channelsLoading}
                    value={deliveryMode}
                    onChange={(event) => {
                      setDirty(true)
                      deliveryTouched.current = true
                      const next = event.target.value as AutomationDeliveryMode
                      setDeliveryMode(next)
                      setDeliveryTarget(next === 'feishu' ? feishuDefault : next === 'email' ? emailDefault : '')
                    }}
                    wrapperClassName="automation-editor__select h-10 rounded-lg"
                  >
                    <option value="none">{t('automationDeliveryNone')}</option>
                    <option value="feishu">{t('automationDeliveryFeishu')}</option>
                    <option value="wecom">{t('automationDeliveryWecom')}</option>
                    <option value="email">{t('automationDeliveryEmail')}</option>
                  </SettingsSelect>
                </label>
                <div className="flex min-h-[52px] min-w-0 items-center break-all">
                  {channelsLoading ? (
                    <Loader2 aria-label={t('automationLoadingChannels')} className="h-4 w-4 animate-spin text-ds-muted" />
                  ) : deliveryMode === 'none' ? (
                    <span className="text-[13px] text-ds-faint">{t('automationDeliveryNoneHint')}</span>
                  ) : deliveryMode === 'feishu' ? (
                    feishuChannelReady ? (
                      <span className="text-[13px] text-emerald-700 dark:text-emerald-300">
                        {t('automationDeliveryFeishuBoundHint')} · {deliveryTarget || feishuDefault}
                      </span>
                    ) : (
                      <span className="flex flex-wrap items-center gap-2 text-[13px] text-amber-700 dark:text-amber-300">
                        <span>{t('automationDeliveryFeishuNotConfigured')}</span>
                        <button
                          type="button"
                          disabled={submitting}
                        onClick={() => leave(() => setRoute('channels'))}
                          className="rounded-md border border-amber-300/70 px-2 py-0.5 text-[12px] font-medium hover:bg-amber-100/60 dark:border-amber-700/60 dark:hover:bg-amber-950/30"
                        >
                          {t('automationOpenChannelCenter')}
                        </button>
                      </span>
                    )
                  ) : deliveryMode === 'wecom' ? (
                    wecomChannelReady ? (
                      <span className="text-[13px] text-emerald-700 dark:text-emerald-300">
                        {t('automationDeliveryWecomBoundHint')}
                      </span>
                    ) : (
                      <span className="flex flex-wrap items-center gap-2 text-[13px] text-amber-700 dark:text-amber-300">
                        <span>{t('automationDeliveryWecomNotConfigured')}</span>
                        <button
                          type="button"
                          disabled={submitting}
                        onClick={() => leave(() => setRoute('channels'))}
                          className="rounded-md border border-amber-300/70 px-2 py-0.5 text-[12px] font-medium hover:bg-amber-100/60 dark:border-amber-700/60 dark:hover:bg-amber-950/30"
                        >
                          {t('automationOpenChannelCenter')}
                        </button>
                      </span>
                    )
                  ) : emailChannelReady ? (
                    <span className="text-[13px] text-ds-muted">
                      {t('automationDeliveryEmailBoundHint', { email: deliveryTarget || emailDefault })}
                    </span>
                  ) : (
                    <span className="flex flex-wrap items-center gap-2 text-[13px] text-amber-700 dark:text-amber-300">
                      <span>{t('automationDeliveryEmailNotConfigured')}</span>
                      <button
                        type="button"
                        disabled={submitting}
                        onClick={() => leave(() => setRoute('channels'))}
                        className="rounded-md border border-amber-300/70 px-2 py-0.5 text-[12px] font-medium hover:bg-amber-100/60 dark:border-amber-700/60 dark:hover:bg-amber-950/30"
                      >
                        {t('automationOpenChannelCenter')}
                      </button>
                    </span>
                  )}
                </div>
              </div>
            </div>

            <details className="automation-editor__advanced automation-editor__workspace">
              <summary className="cursor-pointer text-[13px] font-semibold text-ds-ink">
                {t('automationAdvanced')}
              </summary>
              <div className="mt-4 grid gap-4">
                <label className="grid gap-2">
                  <span className="text-[13px] font-semibold text-ds-ink">{t('automationWorkspaceLabel')}</span>
                  <input
                    value={workspaceOverride}
                    onChange={(event) => setWorkspaceOverride(event.target.value)}
                    placeholder={workspaceRoot || t('automationWorkspacePlaceholder')}
                    className="rounded-2xl border border-ds-border bg-ds-card px-4 py-3 font-mono text-[13px] text-ds-ink outline-none placeholder:text-ds-faint focus:border-accent/60"
                  />
                </label>
              </div>
            </details>

            {notice ? (
              <div
                role={notice.tone === 'error' ? 'alert' : 'status'}
                className={`rounded-2xl border px-4 py-3 text-[13px] leading-6 ${
                  notice.tone === 'error'
                    ? 'border-red-300/80 bg-red-50 text-red-800 dark:border-red-800/70 dark:bg-red-950/25 dark:text-red-200'
                    : 'border-emerald-300/80 bg-emerald-50 text-emerald-800 dark:border-emerald-800/70 dark:bg-emerald-950/25 dark:text-emerald-200'
                }`}
              >
                {notice.message}
              </div>
            ) : null}

            <div className="automation-editor__actions flex flex-wrap items-center justify-end gap-2">
              <button
                type="button"
                disabled={submitting}
                onClick={() => leave(onBackToChat)}
                className="rounded-xl border border-ds-border px-4 py-2 text-[13px] font-semibold text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
              >
                {t('cancel')}
              </button>
              <button
                type="button"
                disabled={!runtimeReady || submitting || channelsLoading || Boolean(created)}
                onClick={() => void submit()}
                className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-[13px] font-semibold text-accent-foreground shadow-sm transition hover:bg-accent/90 disabled:opacity-60"
              >
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <CalendarClock className="h-4 w-4" />}
                {initialAutomation ? t('automationSave') : t('automationCreate')}
              </button>
            </div>
          </fieldset>
        </div>
      </div>
    </div>
  )
}

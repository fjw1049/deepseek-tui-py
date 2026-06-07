import { useEffect, useMemo, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ArrowLeft,
  CalendarClock,
  CheckCircle2,
  Loader2,
  Play,
  Settings,
  Sparkles
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
  type AutomationDeliveryMode,
  type AutomationScheduleKind,
  type WeekdayToken
} from '../../lib/automation-task-form-model'
import { resolveAutomationFeishuChatId } from '../../lib/resolve-automation-feishu-chat-id'
import { resolveAutomationMailTo } from '../../lib/resolve-automation-mail-to'

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
  MO: 'automationWeekdayMo',
  TU: 'automationWeekdayTu',
  WE: 'automationWeekdayWe',
  TH: 'automationWeekdayTh',
  FR: 'automationWeekdayFr',
  SA: 'automationWeekdaySa',
  SU: 'automationWeekdaySu'
}

function defaultOnceAt(): string {
  const date = new Date(Date.now() + 60 * 60 * 1000)
  const offsetMs = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16)
}

function errorKey(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error)
  if (
    message === 'prompt_required' ||
    message === 'once_at_invalid' ||
    message === 'interval_invalid' ||
    message === 'time_of_day_invalid' ||
    message === 'weekdays_required' ||
    message === 'rrule_required'
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
  const [name, setName] = useState(initialAutomation?.name ?? '')
  const [prompt, setPrompt] = useState(initialAutomation?.prompt ?? '')
  const [scheduleKind, setScheduleKind] = useState<AutomationScheduleKind>(initialAutomation ? 'custom' : 'daily')
  const [onceAt, setOnceAt] = useState(defaultOnceAt)
  const [everyHours, setEveryHours] = useState('1')
  const [timeOfDay, setTimeOfDay] = useState('09:00')
  const [weekdays, setWeekdays] = useState<WeekdayToken[]>(['MO', 'TU', 'WE', 'TH', 'FR'])
  const [customRrule, setCustomRrule] = useState(initialAutomation?.rrule ?? '')
  const [workspaceOverride, setWorkspaceOverride] = useState(initialAutomation?.cwds?.[0] ?? workspaceRoot)
  const initialDeliveryMode: AutomationDeliveryMode =
    initialAutomation?.delivery?.mode === 'feishu' || initialAutomation?.delivery?.mode === 'email'
      ? initialAutomation.delivery.mode
      : 'none'
  const [deliveryMode, setDeliveryMode] = useState<AutomationDeliveryMode>(initialDeliveryMode)
  const [deliveryTarget, setDeliveryTarget] = useState(initialAutomation?.delivery?.to ?? '')
  const [feishuDefault, setFeishuDefault] = useState('')
  const [emailDefault, setEmailDefault] = useState('')
  const [createPaused, setCreatePaused] = useState(initialAutomation?.status === 'paused')
  const [submitting, setSubmitting] = useState(false)
  const [runningNow, setRunningNow] = useState(false)
  const [created, setCreated] = useState<AutomationRecord | null>(null)
  const [notice, setNotice] = useState<{ tone: 'success' | 'error'; message: string } | null>(null)

  useEffect(() => {
    setWorkspaceOverride((current) => current || workspaceRoot)
  }, [workspaceRoot])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      const [feishu, mail] = await Promise.all([
        resolveAutomationFeishuChatId(),
        resolveAutomationMailTo()
      ])
      if (cancelled) return
      setFeishuDefault(feishu ?? '')
      setEmailDefault(mail ?? '')
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (deliveryMode === 'feishu') setDeliveryTarget((current) => current || feishuDefault)
    if (deliveryMode === 'email') setDeliveryTarget((current) => current || emailDefault)
    if (deliveryMode === 'none') setDeliveryTarget('')
  }, [deliveryMode, emailDefault, feishuDefault])

  const scheduleHint = useMemo(() => {
    if (scheduleKind === 'once') return t('automationScheduleOnceHint')
    if (scheduleKind === 'hourly') return t('automationScheduleHourlyHint')
    if (scheduleKind === 'daily') return t('automationScheduleDailyHint')
    if (scheduleKind === 'weekly') return t('automationScheduleWeeklyHint')
    return t('automationScheduleCustomHint')
  }, [scheduleKind, t])

  const toggleWeekday = (day: WeekdayToken): void => {
    setWeekdays((current) =>
      current.includes(day) ? current.filter((item) => item !== day) : [...current, day]
    )
  }

  const submit = async (): Promise<void> => {
    if (!runtimeReady || submitting) return
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
          customRrule
        },
        deliveryMode,
        deliveryTarget,
        createPaused
      })
      const record = initialAutomation
        ? await updateAutomation(initialAutomation.id, {
            ...input,
            delivery: input.delivery ?? {}
          })
        : await createAutomation(input)
      if (onSaved) {
        onSaved(record)
        return
      }
      setCreated(record)
      setNotice({ tone: 'success', message: t('automationCreateSuccess', { name: record.name }) })
    } catch (err) {
      const key = errorKey(err)
      setNotice({
        tone: 'error',
        message: key.startsWith('common:') ? t(key.slice('common:'.length)) : key
      })
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
      setNotice({ tone: 'error', message: err instanceof Error ? err.message : String(err) })
    } finally {
      setRunningNow(false)
    }
  }

  return (
    <div className="ds-no-drag flex min-h-0 flex-1 overflow-y-auto px-5 py-6 md:px-10 lg:px-16">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <button
              type="button"
              onClick={onBackToChat}
              className="mb-4 inline-flex items-center gap-1.5 rounded-full border border-ds-border bg-ds-card px-3 py-1.5 text-[13px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              {t('automationBackToChat')}
            </button>
            <div className="inline-flex items-center gap-2 rounded-full bg-accent/10 px-3 py-1 text-[12px] font-semibold text-accent">
              <Sparkles className="h-3.5 w-3.5" />
              {initialAutomation ? t('automationEditBadge') : t('automationTaskBadge')}
            </div>
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
          <div className="rounded-[28px] border border-emerald-300/70 bg-emerald-50/80 p-5 text-emerald-900 shadow-sm dark:border-emerald-800/70 dark:bg-emerald-950/25 dark:text-emerald-100">
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

        <div className="rounded-[30px] border border-ds-border bg-ds-card/95 p-5 shadow-sm">
          <div className="grid gap-5">
            <label className="grid gap-2">
              <span className="text-[13px] font-semibold text-ds-ink">{t('automationPromptLabel')}</span>
              <textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder={t('automationPromptPlaceholder')}
                className="min-h-[132px] resize-y rounded-2xl border border-ds-border bg-ds-main px-4 py-3 text-[14px] leading-6 text-ds-ink outline-none transition placeholder:text-ds-faint focus:border-accent/60"
              />
            </label>

            <div className="grid gap-4 md:grid-cols-[1fr_220px]">
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
                <span className="text-[13px] font-semibold text-ds-ink">{t('automationStatusLabel')}</span>
                <select
                  value={createPaused ? 'paused' : 'active'}
                  onChange={(event) => setCreatePaused(event.target.value === 'paused')}
                  className="rounded-2xl border border-ds-border bg-ds-main px-4 py-3 text-[14px] text-ds-ink outline-none focus:border-accent/60"
                >
                  <option value="active">{t('automationStatusActive')}</option>
                  <option value="paused">{t('automationStatusPaused')}</option>
                </select>
              </label>
            </div>

            <div className="rounded-3xl border border-ds-border-muted bg-ds-main/70 p-4">
              <div className="mb-3 flex items-center gap-2 text-[13px] font-semibold text-ds-ink">
                <CalendarClock className="h-4 w-4 text-accent" />
                {t('automationScheduleLabel')}
              </div>
              <div className="grid gap-3 md:grid-cols-[220px_1fr]">
                <select
                  value={scheduleKind}
                  onChange={(event) => setScheduleKind(event.target.value as AutomationScheduleKind)}
                  className="rounded-2xl border border-ds-border bg-ds-card px-4 py-3 text-[14px] text-ds-ink outline-none focus:border-accent/60"
                >
                  <option value="once">{t('automationScheduleOnce')}</option>
                  <option value="hourly">{t('automationScheduleHourly')}</option>
                  <option value="daily">{t('automationScheduleDaily')}</option>
                  <option value="weekly">{t('automationScheduleWeekly')}</option>
                  <option value="custom">{t('automationScheduleCustom')}</option>
                </select>
                <div className="grid gap-3">
                  {scheduleKind === 'once' ? (
                    <input
                      type="datetime-local"
                      value={onceAt}
                      onChange={(event) => setOnceAt(event.target.value)}
                      className="rounded-2xl border border-ds-border bg-ds-card px-4 py-3 text-[14px] text-ds-ink outline-none focus:border-accent/60"
                    />
                  ) : null}
                  {scheduleKind === 'hourly' ? (
                    <input
                      type="number"
                      min={1}
                      value={everyHours}
                      onChange={(event) => setEveryHours(event.target.value)}
                      className="rounded-2xl border border-ds-border bg-ds-card px-4 py-3 text-[14px] text-ds-ink outline-none focus:border-accent/60"
                    />
                  ) : null}
                  {scheduleKind === 'daily' || scheduleKind === 'weekly' ? (
                    <input
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
                          onClick={() => toggleWeekday(day)}
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
                  {scheduleKind === 'custom' ? (
                    <input
                      value={customRrule}
                      onChange={(event) => setCustomRrule(event.target.value)}
                      placeholder="FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=30"
                      className="rounded-2xl border border-ds-border bg-ds-card px-4 py-3 font-mono text-[13px] text-ds-ink outline-none placeholder:text-ds-faint focus:border-accent/60"
                    />
                  ) : null}
                  <p className="text-[12px] leading-5 text-ds-faint">{scheduleHint}</p>
                </div>
              </div>
            </div>

            <div className="rounded-3xl border border-ds-border-muted bg-ds-main/70 p-4">
              <div className="mb-3 text-[13px] font-semibold text-ds-ink">{t('automationDeliveryLabel')}</div>
              <div className="grid gap-3 md:grid-cols-[220px_1fr]">
                <label className="grid gap-2">
                  <select
                    value={deliveryMode}
                    onChange={(event) => setDeliveryMode(event.target.value as AutomationDeliveryMode)}
                    className="rounded-2xl border border-ds-border bg-ds-card px-4 py-3 text-[14px] text-ds-ink outline-none focus:border-accent/60"
                  >
                    <option value="none">{t('automationDeliveryNone')}</option>
                    <option value="feishu">{t('automationDeliveryFeishu')}</option>
                    <option value="email">{t('automationDeliveryEmail')}</option>
                  </select>
                </label>
                <label className="grid gap-2">
                  <input
                    value={deliveryTarget}
                    disabled={deliveryMode === 'none'}
                    onChange={(event) => setDeliveryTarget(event.target.value)}
                    placeholder={t('automationDeliveryTargetPlaceholder')}
                    aria-label={t('automationDeliveryTarget')}
                    className="rounded-2xl border border-ds-border bg-ds-card px-4 py-3 text-[14px] text-ds-ink outline-none placeholder:text-ds-faint focus:border-accent/60 disabled:opacity-50"
                  />
                </label>
              </div>
            </div>

            <details className="rounded-3xl border border-ds-border-muted bg-ds-main/50 p-4">
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
                className={`rounded-2xl border px-4 py-3 text-[13px] leading-6 ${
                  notice.tone === 'error'
                    ? 'border-red-300/80 bg-red-50 text-red-800 dark:border-red-800/70 dark:bg-red-950/25 dark:text-red-200'
                    : 'border-emerald-300/80 bg-emerald-50 text-emerald-800 dark:border-emerald-800/70 dark:bg-emerald-950/25 dark:text-emerald-200'
                }`}
              >
                {notice.message}
              </div>
            ) : null}

            <div className="flex flex-wrap items-center justify-end gap-2 border-t border-ds-border-muted pt-4">
              <button
                type="button"
                onClick={onBackToChat}
                className="rounded-xl border border-ds-border px-4 py-2 text-[13px] font-semibold text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
              >
                {t('cancel')}
              </button>
              <button
                type="button"
                disabled={!runtimeReady || submitting}
                onClick={() => void submit()}
                className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-[13px] font-semibold text-white shadow-sm transition hover:bg-accent/90 disabled:opacity-60"
              >
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <CalendarClock className="h-4 w-4" />}
                {initialAutomation ? t('automationSave') : t('automationCreate')}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

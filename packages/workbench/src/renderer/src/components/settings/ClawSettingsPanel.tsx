import type { ReactElement } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  CalendarClock,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Trash2,
  Zap
} from 'lucide-react'
import type { AppSettingsV1, ClawSettingsPatchV1, ClawTaskV1 } from '@shared/app-settings'
import {
  automationIdFromClawTask,
  deleteAutomation,
  formatAutomationRrule,
  formatAutomationWhen,
  listAutomations,
  pauseAutomation,
  resumeAutomation,
  runAutomationNow,
  type AutomationRecord
} from '../../lib/automation-runtime-client'
import { useChatStore } from '../../store/chat-store'
import { ClawFeishuSection } from './ClawFeishuSection'

type InlineNotice = {
  tone: 'success' | 'error' | 'info'
  message: string
}

type Props = {
  form: AppSettingsV1
  onClawPatch: (patch: ClawSettingsPatchV1) => void
}

function Toggle({
  checked,
  onChange
}: {
  checked: boolean
  onChange: (v: boolean) => void
}): ReactElement {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative h-7 w-12 shrink-0 rounded-full transition ${
        checked ? 'bg-emerald-500' : 'bg-ds-faint'
      }`}
    >
      <span
        className={`absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition ${
          checked ? 'left-[22px]' : 'left-0.5'
        }`}
      />
    </button>
  )
}

function pruneClawTasks(tasks: ClawTaskV1[], liveIds: Set<string>): ClawTaskV1[] {
  return tasks.filter((task) => {
    const aid = automationIdFromClawTask(task.lastMessage)
    return aid != null && liveIds.has(aid)
  })
}

export function ClawSettingsPanel({ form, onClawPatch }: Props): ReactElement {
  const { t } = useTranslation('settings')
  const { t: tCommon } = useTranslation('common')
  const runtimeConnection = useChatStore((s) => s.runtimeConnection)
  const openSettings = useChatStore((s) => s.openSettings)
  const setRoute = useChatStore((s) => s.setRoute)

  const [automations, setAutomations] = useState<AutomationRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [notice, setNotice] = useState<InlineNotice | null>(null)

  const runtimeReady = runtimeConnection === 'ready'
  const runtimePort = form.deepseek.port
  const defaultWorkspace =
    form.claw.im.workspaceRoot.trim() || form.workspaceRoot.trim() || '~/.deepseekgui/default_workspace'

  const refresh = useCallback(async () => {
    if (!runtimeReady) {
      setAutomations([])
      return
    }
    setLoading(true)
    setNotice(null)
    try {
      const rows = await listAutomations()
      setAutomations(rows)
      const liveIds = new Set(rows.map((r) => r.id))
      const pruned = pruneClawTasks(form.claw.tasks, liveIds)
      if (pruned.length !== form.claw.tasks.length) {
        onClawPatch({ tasks: pruned })
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setNotice({ tone: 'error', message })
      setAutomations([])
    } finally {
      setLoading(false)
    }
  }, [form.claw.tasks, onClawPatch, runtimeReady])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const clawByAutomationId = useMemo(() => {
    const map = new Map<string, ClawTaskV1>()
    for (const task of form.claw.tasks) {
      const aid = automationIdFromClawTask(task.lastMessage)
      if (aid) map.set(aid, task)
    }
    return map
  }, [form.claw.tasks])

  const removeClawTaskForAutomation = (automationId: string): void => {
    onClawPatch({
      tasks: form.claw.tasks.filter((task) => automationIdFromClawTask(task.lastMessage) !== automationId)
    })
  }

  const handlePauseResume = async (row: AutomationRecord): Promise<void> => {
    setBusyId(row.id)
    setNotice(null)
    try {
      const updated =
        row.status === 'active'
          ? await pauseAutomation(row.id)
          : await resumeAutomation(row.id)
      setAutomations((prev) => prev.map((a) => (a.id === updated.id ? updated : a)))
      setNotice({
        tone: 'success',
        message:
          updated.status === 'active'
            ? t('clawTaskResumed', { name: updated.name })
            : t('clawTaskPaused', { name: updated.name })
      })
    } catch (err) {
      setNotice({ tone: 'error', message: err instanceof Error ? err.message : String(err) })
    } finally {
      setBusyId(null)
    }
  }

  const handleRunNow = async (row: AutomationRecord): Promise<void> => {
    setBusyId(row.id)
    setNotice(null)
    try {
      const run = await runAutomationNow(row.id)
      setNotice({
        tone: 'success',
        message: t('clawTaskRunStarted', {
          name: row.name,
          taskId: run.task_id ?? '—'
        })
      })
    } catch (err) {
      setNotice({ tone: 'error', message: err instanceof Error ? err.message : String(err) })
    } finally {
      setBusyId(null)
    }
  }

  const handleDelete = async (row: AutomationRecord): Promise<void> => {
    if (!window.confirm(t('clawTaskDeleteConfirm', { name: row.name }))) return
    setBusyId(row.id)
    setNotice(null)
    try {
      await deleteAutomation(row.id)
      removeClawTaskForAutomation(row.id)
      setAutomations((prev) => prev.filter((a) => a.id !== row.id))
      setNotice({ tone: 'success', message: t('clawTaskDeleted', { name: row.name }) })
    } catch (err) {
      setNotice({ tone: 'error', message: err instanceof Error ? err.message : String(err) })
    } finally {
      setBusyId(null)
    }
  }

  const goCreateAutomation = (): void => {
    setRoute('automation')
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-2xl border border-ds-border bg-ds-card/95 shadow-sm">
        <div className="border-b border-ds-border-muted px-5 py-3">
          <h2 className="text-[16px] font-semibold text-ds-ink">{t('clawRuntime')}</h2>
          <p className="mt-1 text-[13px] leading-6 text-ds-muted">{t('clawEnabledDesc')}</p>
        </div>
        <div className="flex items-center justify-between gap-4 px-5 py-4">
          <div>
            <div className="text-[14px] font-medium text-ds-ink">{t('clawEnabled')}</div>
            <div className="mt-0.5 text-[12px] text-ds-faint">{tCommon('clawMasterSwitchHint')}</div>
          </div>
          <Toggle
            checked={form.claw.enabled}
            onChange={(enabled) => onClawPatch({ enabled })}
          />
        </div>
      </div>

      <ClawFeishuSection
        form={form}
        runtimeReady={runtimeReady}
        runtimePort={runtimePort}
        onClawPatch={onClawPatch}
      />

      <div className="rounded-2xl border border-ds-border bg-ds-card/95 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ds-border-muted px-5 py-3">
          <div>
            <h2 className="text-[16px] font-semibold text-ds-ink">{t('clawTasksTitle')}</h2>
            <p className="mt-1 text-[13px] text-ds-muted">{t('clawTasksDesc')}</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={!runtimeReady || loading}
              onClick={() => void refresh()}
              className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-ds-border bg-ds-main px-3 py-1.5 text-center text-[13px] font-medium leading-none text-ds-ink transition hover:bg-ds-hover disabled:opacity-50"
            >
              {loading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              {t('clawTasksRefresh')}
            </button>
            <button
              type="button"
              onClick={goCreateAutomation}
              className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-accent/25 bg-accent/10 px-3 py-1.5 text-center text-[13px] font-medium leading-none text-accent transition hover:bg-accent/15"
            >
              <CalendarClock className="h-3.5 w-3.5" />
              {t('clawTaskAddFromComposer')}
            </button>
          </div>
        </div>

        {!runtimeReady ? (
          <div className="px-5 py-8 text-center text-[13px] leading-6 text-ds-muted">
            {t('clawTasksNeedRuntime')}
            <button
              type="button"
              className="mt-3 block w-full text-accent underline-offset-2 hover:underline"
              onClick={() => openSettings('runtime')}
            >
              {t('clawTasksOpenRuntime')}
            </button>
          </div>
        ) : loading && automations.length === 0 ? (
          <div className="flex items-center justify-center gap-2 px-5 py-10 text-[13px] text-ds-muted">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('loading')}
          </div>
        ) : automations.length === 0 ? (
          <div className="px-5 py-8 text-center text-[13px] leading-6 text-ds-muted">
            {t('clawTasksEmpty')}
            <p className="mt-2 text-[12px] text-ds-faint">{t('clawTasksEmptyHint')}</p>
          </div>
        ) : (
          <ul className="divide-y divide-ds-border-muted">
            {automations.map((row) => {
              const claw = clawByAutomationId.get(row.id)
              const scheduleLabel = formatAutomationRrule(row.rrule)
              const isBusy = busyId === row.id
              const isActive = row.status === 'active'
              return (
                <li key={row.id} className="px-5 py-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[15px] font-semibold text-ds-ink">{row.name}</span>
                        <span
                          className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                            isActive
                              ? 'bg-emerald-500/12 text-emerald-700 dark:text-emerald-200'
                              : 'bg-ds-subtle text-ds-muted'
                          }`}
                        >
                          {isActive ? t('clawAutomationActive') : t('clawAutomationPaused')}
                        </span>
                      </div>
                      {claw?.prompt ? (
                        <p className="mt-1 line-clamp-2 text-[13px] text-ds-muted">{claw.prompt}</p>
                      ) : (
                        <p className="mt-1 line-clamp-2 text-[13px] text-ds-faint">{row.prompt}</p>
                      )}
                      <dl className="mt-2 grid gap-1 text-[12px] text-ds-faint sm:grid-cols-2">
                        <div>
                          <span className="text-ds-muted">{t('clawTaskSchedule')}：</span>
                          {scheduleLabel}
                        </div>
                        <div>
                          <span className="text-ds-muted">{t('clawNextRun')}：</span>
                          {formatAutomationWhen(row.next_run_at)}
                        </div>
                        <div>
                          <span className="text-ds-muted">{t('clawTaskLastRun')}：</span>
                          {formatAutomationWhen(row.last_run_at)}
                        </div>
                        <div>
                          <span className="text-ds-muted">{t('clawTaskDelivery')}：</span>
                          {row.delivery?.to ?? row.delivery?.mode ?? '—'}
                        </div>
                      </dl>
                    </div>
                    <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                      <button
                        type="button"
                        disabled={isBusy}
                        title={t('clawRunNow')}
                        onClick={() => void handleRunNow(row)}
                        className="inline-flex items-center justify-center rounded-lg border border-ds-border p-2 text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50"
                      >
                        <Zap className="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        disabled={isBusy}
                        title={isActive ? t('clawPause') : t('clawResume')}
                        onClick={() => void handlePauseResume(row)}
                        className="inline-flex items-center justify-center rounded-lg border border-ds-border p-2 text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50"
                      >
                        {isActive ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                      </button>
                      <button
                        type="button"
                        disabled={isBusy}
                        title={t('clawTaskDelete')}
                        onClick={() => void handleDelete(row)}
                        className="inline-flex items-center justify-center rounded-lg border border-red-500/25 p-2 text-red-600 transition hover:bg-red-500/10 disabled:opacity-50 dark:text-red-300"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
        <div className="border-t border-ds-border-muted px-5 py-3 text-[12px] text-ds-faint">
          {t('clawTasksCount', { count: automations.length })} · {t('clawDefaultWorkspace')}:{' '}
          <span className="font-mono text-ds-muted">{defaultWorkspace}</span>
        </div>
      </div>

      {notice ? (
        <div
          className={`rounded-xl border px-4 py-3 text-[13px] leading-6 ${
            notice.tone === 'error'
              ? 'border-red-300/80 bg-red-50 text-red-800 dark:border-red-800/70 dark:bg-red-950/25 dark:text-red-200'
              : 'border-emerald-300/80 bg-emerald-50 text-emerald-800 dark:border-emerald-800/70 dark:bg-emerald-950/25 dark:text-emerald-200'
          }`}
        >
          {notice.message}
        </div>
      ) : null}
    </div>
  )
}

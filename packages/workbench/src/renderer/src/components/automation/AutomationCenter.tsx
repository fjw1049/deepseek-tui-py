import { useCallback, useEffect, useMemo, useState, type ReactElement } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import {
  CalendarClock,
  Info,
  Loader2,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
  Zap
} from 'lucide-react'
import {
  createAutomation,
  deleteAutomation,
  formatAutomationRrule,
  formatAutomationWhen,
  listAutomationRuns,
  listAutomations,
  pauseAutomation,
  resumeAutomation,
  runAutomationNow,
  updateAutomation,
  type AutomationRecord,
  type AutomationRunRecord
} from '../../lib/automation-runtime-client'
import { formatRunDeliveryStatus } from '../../lib/automation-run-display'
import { ALL_WEEKDAYS } from '../../lib/automation-task-form-model'
import {
  automationCardPreview,
  automationDeliveryCardHint,
  automationDeliveryDetail
} from '../../lib/automation-list-display'
import {
  loadChannelDeliveryState,
  resolveDefaultDeliveryFromChannels,
  templateDeliveryCardHint,
  type ChannelDeliveryState
} from '../../lib/resolve-channel-delivery'
import { AutomationListCard } from './AutomationListCard'
import { AutomationTaskForm } from './AutomationTaskForm'

type Props = {
  runtimeReady: boolean
  workspaceRoot: string
  onOpenRuntimeSettings: () => void
}

type Notice = { tone: 'success' | 'error'; message: string }
type StatusFilter = 'all' | 'active' | 'paused'
type SortMode = 'active-first' | 'newest'
type TabId = 'tasks' | 'runs'
type AnnotatedRun = AutomationRunRecord & { automationName: string }

type TaskTemplate = {
  id: string
  icon: string
  name: string
  desc: string
  prompt: string
  badge: string
  rrule: string
  useCwd: boolean
}

const TEMPLATES: TaskTemplate[] = [
  {
    id: 'daily-downloads',
    icon: '🗂️',
    name: '每日下载文件夹整理建议',
    desc: '扫描 ~/Downloads，按类型分组并标注大文件，不自动删除',
    badge: '每天 18:00',
    prompt: [
      '请帮我检查并整理下载文件夹：',
      '1. 执行 ls -lhS ~/Downloads/ 列出所有文件（按大小排序）',
      '2. 按文件类型分组：文档(.pdf/.doc/.xlsx)、图片(.jpg/.png)、压缩包(.zip/.tar/.gz)、安装包(.dmg/.pkg/.app)、其他',
      '3. 统计各分组的文件数量和总大小',
      '4. 对超过 500MB 的大文件特别标注',
      '5. 给出整理建议，但不要自动删除或移动任何文件'
    ].join('\n'),
    rrule: `FREQ=WEEKLY;BYDAY=${ALL_WEEKDAYS.join(',')};BYHOUR=18;BYMINUTE=0`,
    useCwd: false
  },
  {
    id: 'daily-system',
    icon: '🖥️',
    name: '每日系统资源报告',
    desc: '检查磁盘、内存、高 CPU 进程，提示缓存清理建议',
    badge: '每天 08:00',
    prompt: [
      '请帮我检查当前系统资源使用情况：',
      '1. 执行 df -h 检查磁盘使用率，标注使用超过 80% 的分区',
      '2. 检查内存使用情况（macOS 用 vm_stat，Linux 用 free -h）',
      '3. 列出占用 CPU 最高的前 5 个进程',
      '4. 检查 ~/Library/Caches 和 /tmp 目录大小，提示清理建议',
      '5. 将报告格式化为清晰的 Markdown 表格'
    ].join('\n'),
    rrule: `FREQ=WEEKLY;BYDAY=${ALL_WEEKDAYS.join(',')};BYHOUR=8;BYMINUTE=0`,
    useCwd: false
  }
]

function runTone(status: string): string {
  if (status === 'succeeded' || status === 'success')
    return 'text-emerald-700 dark:text-emerald-300'
  if (status === 'failed' || status === 'error') return 'text-red-700 dark:text-red-300'
  if (status === 'running') return 'text-accent'
  return 'text-ds-muted'
}

export function AutomationCenter({
  runtimeReady,
  workspaceRoot,
  onOpenRuntimeSettings
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<AutomationRecord | null>(null)
  const [rows, setRows] = useState<AutomationRecord[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [runs, setRuns] = useState<AutomationRunRecord[]>([])
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<StatusFilter>('all')
  const [loading, setLoading] = useState(false)
  const [runsLoading, setRunsLoading] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [tab, setTab] = useState<TabId>('tasks')
  const [sort, setSort] = useState<SortMode>('active-first')
  const [menuId, setMenuId] = useState<string | null>(null)
  const [templateBusy, setTemplateBusy] = useState<string | null>(null)
  const [allRuns, setAllRuns] = useState<AnnotatedRun[]>([])
  const [allRunsLoading, setAllRunsLoading] = useState(false)
  const [channelDelivery, setChannelDelivery] = useState<ChannelDeliveryState | null>(null)

  const selected = rows.find((row) => row.id === selectedId) ?? null
  const automationById = useMemo(() => new Map(rows.map((row) => [row.id, row])), [rows])

  const templateTaskMap = useMemo(() => {
    const map = new Map<string, AutomationRecord>()
    for (const tpl of TEMPLATES) {
      const match = rows.find((r) => r.name === tpl.name)
      if (match) map.set(tpl.id, match)
    }
    return map
  }, [rows])

  const sortedTemplates = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    const list = TEMPLATES.filter((tpl) => !templateTaskMap.has(tpl.id)).filter((tpl) => {
      if (status === 'paused') return false
      if (normalized) {
        const haystack = `${tpl.name} ${tpl.desc}`.toLowerCase()
        if (!haystack.includes(normalized)) return false
      }
      return true
    })
    return list
  }, [templateTaskMap, query, status])

  const customFiltered = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    const list = rows.filter((row) => {
      if (status !== 'all' && row.status !== status) return false
      return (
        !normalized ||
        row.name.toLowerCase().includes(normalized) ||
        row.prompt.toLowerCase().includes(normalized)
      )
    })
    if (sort === 'active-first') {
      list.sort((a, b) => {
        const aActive = a.status === 'active' ? 0 : 1
        const bActive = b.status === 'active' ? 0 : 1
        if (aActive !== bActive) return aActive - bActive
        const aTime = a.created_at ? new Date(a.created_at).getTime() : 0
        const bTime = b.created_at ? new Date(b.created_at).getTime() : 0
        return bTime - aTime
      })
    } else {
      list.sort((a, b) => {
        const aTime = a.created_at ? new Date(a.created_at).getTime() : 0
        const bTime = b.created_at ? new Date(b.created_at).getTime() : 0
        return bTime - aTime
      })
    }
    return list
  }, [query, rows, status, sort])

  const refresh = useCallback(async () => {
    if (!runtimeReady) {
      setRows([])
      return
    }
    setLoading(true)
    try {
      setRows(await listAutomations())
    } catch (error) {
      setNotice({
        tone: 'error',
        message: error instanceof Error ? error.message : String(error)
      })
    } finally {
      setLoading(false)
    }
  }, [runtimeReady])

  const refreshRuns = useCallback(async (id: string) => {
    setRunsLoading(true)
    try {
      setRuns(await listAutomationRuns(id))
    } catch (error) {
      setNotice({
        tone: 'error',
        message: error instanceof Error ? error.message : String(error)
      })
      setRuns([])
    } finally {
      setRunsLoading(false)
    }
  }, [])

  const fetchAllRuns = useCallback(async () => {
    if (!rows.length) {
      setAllRuns([])
      return
    }
    setAllRunsLoading(true)
    try {
      const nameMap = new Map(rows.map((r) => [r.id, r.name]))
      const collected: AnnotatedRun[] = []
      await Promise.all(
        rows.map(async (row) => {
          try {
            const batch = await listAutomationRuns(row.id, 10)
            collected.push(
              ...batch.map((r) => ({
                ...r,
                automationName: nameMap.get(r.automation_id) || '—'
              }))
            )
          } catch {
            /* skip automations whose runs can't be fetched */
          }
        })
      )
      collected.sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      )
      setAllRuns(collected.slice(0, 100))
    } catch {
      setAllRuns([])
    } finally {
      setAllRunsLoading(false)
    }
  }, [rows])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    let cancelled = false
    void loadChannelDeliveryState()
      .then((state) => {
        if (!cancelled) setChannelDelivery(state)
      })
      .catch(() => {
        if (!cancelled) setChannelDelivery(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (selectedId) void refreshRuns(selectedId)
    else setRuns([])
  }, [refreshRuns, selectedId])

  useEffect(() => {
    if (tab === 'runs') void fetchAllRuns()
  }, [tab, fetchAllRuns])

  const mutate = async (
    row: AutomationRecord,
    action: 'toggle' | 'run' | 'delete'
  ): Promise<void> => {
    if (action === 'delete' && !window.confirm(t('automationDeleteConfirm', { name: row.name })))
      return
    setBusyId(row.id)
    setNotice(null)
    try {
      if (action === 'run') {
        await runAutomationNow(row.id)
        setNotice({ tone: 'success', message: t('automationStartedMsg', { name: row.name }) })
        if (selectedId === row.id) await refreshRuns(row.id)
      } else if (action === 'delete') {
        await deleteAutomation(row.id)
        setSelectedId((current) => (current === row.id ? null : current))
        setRows((current) => current.filter((item) => item.id !== row.id))
      } else {
        const next =
          row.status === 'active'
            ? await pauseAutomation(row.id)
            : await resumeAutomation(row.id)
        setRows((current) => current.map((item) => (item.id === next.id ? next : item)))
      }
    } catch (error) {
      setNotice({
        tone: 'error',
        message: error instanceof Error ? error.message : String(error)
      })
    } finally {
      setBusyId(null)
    }
  }

  const handleSaved = useCallback(
    (_record: AutomationRecord) => {
      setCreating(false)
      setEditing(null)
      setSelectedId(null)
      void refresh()
    },
    [refresh]
  )

  const enableTemplate = async (tpl: TaskTemplate): Promise<void> => {
    if (templateBusy) return
    const existing = templateTaskMap.get(tpl.id)
    setTemplateBusy(tpl.id)
    setNotice(null)
    try {
      const state = channelDelivery ?? (await loadChannelDeliveryState())
      if (!channelDelivery) setChannelDelivery(state)
      const delivery = resolveDefaultDeliveryFromChannels(state)
      if (existing) {
        if (existing.status !== 'active') await resumeAutomation(existing.id)
        if (delivery && !existing.delivery?.mode) {
          await updateAutomation(existing.id, { delivery })
        }
      } else {
        await createAutomation({
          name: tpl.name,
          prompt: tpl.prompt,
          rrule: tpl.rrule,
          cwds: tpl.useCwd && workspaceRoot ? [workspaceRoot] : [],
          status: 'active',
          ...(delivery ? { delivery } : {})
        })
      }
      void refresh()
    } catch (error) {
      setNotice({
        tone: 'error',
        message: error instanceof Error ? error.message : String(error)
      })
    } finally {
      setTemplateBusy(null)
    }
  }

  if (creating || editing) {
    return (
      <AutomationTaskForm
        runtimeReady={runtimeReady}
        workspaceRoot={workspaceRoot}
        initialAutomation={editing}
        onBackToChat={() => {
          setCreating(false)
          setEditing(null)
        }}
        onOpenAutomationSettings={() => {
          setCreating(false)
          setEditing(null)
          void refresh()
        }}
        onOpenRuntimeSettings={onOpenRuntimeSettings}
        onSaved={handleSaved}
      />
    )
  }

  return (
    <div className="ds-feature-page ds-automation-page ds-no-drag relative flex h-full min-h-0 flex-col">
      {/* Header */}
      <header className="shrink-0 px-8 pt-8">
        <div className="mx-auto flex max-w-6xl items-start justify-between gap-4">
          <div>
            <h1 className="text-[24px] font-semibold text-ds-ink">
              {t('automationCenterTitle')}
            </h1>
            <p className="mt-1 text-[13px] text-ds-muted">{t('automationCenterDesc')}</p>
          </div>
          <button
            type="button"
            disabled={!runtimeReady}
            onClick={() => setCreating(true)}
            className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-[13px] font-medium text-white transition hover:opacity-90 disabled:opacity-40"
          >
            <Plus className="h-4 w-4" />
            {t('automationNewTask')}
          </button>
        </div>
      </header>

      {/* Wake hint — same px-8 → max-w-6xl shell as header/tabs/content so left edges align */}
      <div className="mt-4 shrink-0 px-8">
        <div className="mx-auto max-w-6xl">
          <div className="flex items-center gap-2 rounded-lg bg-amber-50/80 px-3 py-2.5 text-[12px] text-amber-800 dark:bg-amber-950/20 dark:text-amber-200">
            <Info className="h-3.5 w-3.5 shrink-0" />
            <span>{t('automationWakeHint')}</span>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="mt-4 shrink-0 px-8">
        <div className="mx-auto flex max-w-6xl gap-6 border-b border-ds-border-muted">
          <button
            className={`relative pb-3 text-[14px] font-medium transition ${
              tab === 'tasks' ? 'text-ds-ink' : 'text-ds-muted hover:text-ds-ink'
            }`}
            onClick={() => setTab('tasks')}
          >
            {t('automationTabTasks')}
            {tab === 'tasks' && (
              <span className="absolute inset-x-0 bottom-0 h-0.5 rounded-full bg-accent" />
            )}
          </button>
          <button
            className={`relative pb-3 text-[14px] font-medium transition ${
              tab === 'runs' ? 'text-ds-ink' : 'text-ds-muted hover:text-ds-ink'
            }`}
            onClick={() => setTab('runs')}
          >
            {t('automationTabRuns')}
            {tab === 'runs' && (
              <span className="absolute inset-x-0 bottom-0 h-0.5 rounded-full bg-accent" />
            )}
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="ds-automation-scroll min-h-0 flex-1 overflow-auto px-8 py-6">
        <div className="mx-auto max-w-6xl">
          {!runtimeReady ? (
            <div className="rounded-xl border border-ds-border bg-ds-card px-6 py-12 text-center">
              <CalendarClock className="mx-auto h-8 w-8 text-ds-faint" />
              <p className="mt-3 text-[14px] text-ds-muted">{t('automationNeedRuntime')}</p>
              <button
                className="mt-4 text-[13px] text-accent"
                onClick={onOpenRuntimeSettings}
              >
                {t('automationOpenRuntime')}
              </button>
            </div>
          ) : tab === 'tasks' ? (
            <>
              {notice && (
                <div
                  className={`mb-4 rounded-lg border px-4 py-3 text-[13px] ${
                    notice.tone === 'error'
                      ? 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-200'
                      : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200'
                  }`}
                >
                  {notice.message}
                </div>
              )}

              <div className="mb-5 flex flex-wrap items-center gap-2">
                <label className="relative flex min-w-[240px] flex-1 items-center">
                  <Search
                    className="pointer-events-none absolute left-0 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ds-faint"
                    strokeWidth={2}
                    aria-hidden
                  />
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder={t('automationSearchTasks')}
                    className="min-w-0 w-full bg-transparent py-2 pl-6 text-[13px] text-ds-ink outline-none placeholder:text-ds-faint"
                  />
                </label>
                <select
                  value={status}
                  onChange={(e) => setStatus(e.target.value as StatusFilter)}
                  className="rounded-lg border border-ds-border bg-ds-card px-3 py-2 text-[13px] text-ds-ink"
                >
                  <option value="all">{t('automationFilterAll')}</option>
                  <option value="active">{t('automationEnabled')}</option>
                  <option value="paused">{t('automationPaused')}</option>
                </select>
                <select
                  value={sort}
                  onChange={(e) => setSort(e.target.value as SortMode)}
                  className="rounded-lg border border-ds-border bg-ds-card px-3 py-2 text-[13px] text-ds-ink"
                >
                  <option value="active-first">{t('automationSortActiveFirst')}</option>
                  <option value="newest">{t('automationSortNewest')}</option>
                </select>
                <button
                  type="button"
                  onClick={() => void refresh()}
                  disabled={loading}
                  title={t('automationRefresh')}
                  className="rounded-lg border border-ds-border bg-ds-card p-2 text-ds-muted hover:bg-ds-hover disabled:opacity-50"
                >
                  <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
                </button>
              </div>

              {loading && rows.length === 0 ? (
                <div className="flex items-center justify-center gap-2 py-16 text-[13px] text-ds-muted">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t('automationLoading')}
                </div>
              ) : (
                <div className="grid auto-rows-auto gap-5 sm:grid-cols-2">
                  {/* Template cards — only tasks not yet created */}
                  {sortedTemplates.map((tpl) => {
                    const busy = templateBusy === tpl.id
                    const deliveryHint = templateDeliveryCardHint(channelDelivery, t)
                    return (
                      <AutomationListCard
                        key={tpl.id}
                        title={tpl.name}
                        preview={tpl.desc}
                        schedule={tpl.badge}
                        deliveryHint={deliveryHint}
                        deliveryTitle={deliveryHint}
                        leading={<span className="text-[24px] leading-none">{tpl.icon}</span>}
                        primaryAction="button"
                        actionBusy={busy}
                        actionLabel={
                          busy ? t('automationCreatingTemplate') : t('automationEnableAction')
                        }
                        onPrimaryAction={() => void enableTemplate(tpl)}
                      />
                    )
                  })}

                  {customFiltered.map((row) => {
                    const active = row.status === 'active'
                    const busy = busyId === row.id
                    const deliveryHint = automationDeliveryCardHint(row, t)
                    return (
                      <AutomationListCard
                        key={row.id}
                        title={row.name}
                        preview={automationCardPreview(row.prompt)}
                        schedule={formatAutomationRrule(row.rrule)}
                        deliveryHint={deliveryHint}
                        deliveryTitle={automationDeliveryDetail(row, t)}
                        groupHover
                        primaryAction="toggle"
                        active={active}
                        actionBusy={busy}
                        onPrimaryAction={() => void mutate(row, 'toggle')}
                        onOpenDetails={() => setSelectedId(row.id)}
                        menu={
                          <div
                            className="relative shrink-0"
                            onClick={(event) => event.stopPropagation()}
                          >
                            <button
                              title={t('automationCardMenu')}
                              onClick={() => setMenuId(menuId === row.id ? null : row.id)}
                              className="rounded-md p-1 text-ds-faint opacity-70 transition hover:bg-ds-hover hover:text-ds-ink hover:opacity-100"
                            >
                              <MoreHorizontal className="h-4 w-4" />
                            </button>
                            {menuId === row.id && (
                              <>
                                <div
                                  className="fixed inset-0 z-50"
                                  onClick={() => setMenuId(null)}
                                />
                                <div className="ds-glass absolute right-0 top-full z-50 mt-1 w-36 overflow-hidden rounded-lg">
                                  <button
                                    className="flex w-full items-center gap-2 px-3 py-2 text-[12px] text-ds-ink hover:bg-ds-hover"
                                    onClick={() => {
                                      setSelectedId(row.id)
                                      setMenuId(null)
                                    }}
                                  >
                                    <Info className="h-3.5 w-3.5" />
                                    {t('automationDetailsAction')}
                                  </button>
                                  <button
                                    className="flex w-full items-center gap-2 px-3 py-2 text-[12px] text-ds-ink hover:bg-ds-hover"
                                    onClick={() => {
                                      setEditing(row)
                                      setMenuId(null)
                                    }}
                                  >
                                    <Pencil className="h-3.5 w-3.5" />
                                    {t('automationEditAction')}
                                  </button>
                                  <button
                                    className="flex w-full items-center gap-2 px-3 py-2 text-[12px] text-ds-ink hover:bg-ds-hover"
                                    disabled={busy}
                                    onClick={() => {
                                      void mutate(row, 'run')
                                      setMenuId(null)
                                    }}
                                  >
                                    <Zap className="h-3.5 w-3.5" />
                                    {t('automationRunNowAction')}
                                  </button>
                                  <button
                                    className="flex w-full items-center gap-2 px-3 py-2 text-[12px] text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/20"
                                    disabled={busy}
                                    onClick={() => {
                                      void mutate(row, 'delete')
                                      setMenuId(null)
                                    }}
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                    {t('automationDeleteAction')}
                                  </button>
                                </div>
                              </>
                            )}
                          </div>
                        }
                      />
                    )
                  })}
                </div>
              )}
            </>
          ) : (
            <>
              {allRunsLoading ? (
                <div className="flex items-center justify-center gap-2 py-16 text-[13px] text-ds-muted">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t('automationLoading')}
                </div>
              ) : allRuns.length === 0 ? (
                <div className="py-16 text-center text-[13px] text-ds-muted">
                  {t('automationAllRunsEmpty')}
                </div>
              ) : (
                <div className="ds-content-card overflow-x-auto rounded-xl">
                  <div className="grid min-w-[700px] grid-cols-[minmax(140px,1.5fr)_80px_150px_150px_80px] gap-3 border-b border-ds-border-muted bg-ds-subtle/40 px-4 py-2 text-[11px] font-semibold text-ds-faint">
                    <span>{t('automationColTask')}</span>
                    <span>{t('automationColStatus')}</span>
                    <span>{t('automationRunScheduled')}</span>
                    <span>{t('automationRunStartedAt')}</span>
                    <span>{t('automationColDelivery')}</span>
                  </div>
                  {allRuns.map((run) => (
                    <div
                      key={run.id}
                      className="grid min-w-[700px] grid-cols-[minmax(140px,1.5fr)_80px_150px_150px_80px] items-center gap-3 border-b border-ds-border-muted px-4 py-3 text-[12px] last:border-b-0"
                    >
                      <span className="truncate text-ds-ink">{run.automationName}</span>
                      <span className={`font-medium ${runTone(run.status)}`}>{run.status}</span>
                      <span className="text-ds-muted">
                        {formatAutomationWhen(run.scheduled_for)}
                      </span>
                      <span className="text-ds-muted">
                        {formatAutomationWhen(run.started_at)}
                      </span>
                      <span className="text-ds-muted">
                        {formatRunDeliveryStatus(
                          run,
                          automationById.get(run.automation_id),
                          t
                        )}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Detail drawer. Portaled to <body>: the page root (.ds-feature-page)
          carries a backdrop-filter, which makes it the containing block for
          fixed descendants and forces a second full-size blur layer — the
          combination flickers the whole window (see .ds-automation-drawer in
          index.css). */}
      {selected
        ? createPortal(
        <>
          <button
            type="button"
            aria-label={t('automationCloseDetail')}
            className="fixed inset-0 z-[80] bg-black/20 dark:bg-black/40"
            onClick={() => setSelectedId(null)}
          />
          <div className="ds-automation-drawer fixed inset-y-0 right-0 z-[90] flex w-full max-w-[440px] flex-col">
            <div className="flex items-start justify-between border-b border-ds-border-muted px-5 py-4">
              <div className="min-w-0">
                <h2 className="truncate text-[16px] font-semibold text-ds-ink">{selected.name}</h2>
                <p className="mt-1 text-[12px] text-ds-muted">
                  {formatAutomationRrule(selected.rrule)} ·{' '}
                  {selected.status === 'active' ? t('automationEnabled') : t('automationPaused')}
                </p>
              </div>
              <button
                type="button"
                title={t('automationCloseDetail')}
                onClick={() => setSelectedId(null)}
                className="inline-flex shrink-0 items-center gap-1 rounded-md border border-ds-border px-2.5 py-1.5 text-[12px] text-ds-muted hover:bg-ds-hover"
              >
                <X className="h-3.5 w-3.5" />
                {t('automationCloseDetail')}
              </button>
            </div>
          <div className="min-h-0 flex-1 overflow-auto p-5">
            <button
              type="button"
              onClick={() => setEditing(selected)}
              className="mb-5 inline-flex items-center gap-1.5 rounded-lg border border-ds-border bg-ds-card px-3 py-2 text-[12px] font-medium text-ds-ink hover:bg-ds-hover"
            >
              <Pencil className="h-3.5 w-3.5" />
              {t('automationEditTask')}
            </button>
            <h3 className="text-[12px] font-semibold text-ds-faint">
              {t('automationPromptSection')}
            </h3>
            <p className="mt-2 whitespace-pre-wrap text-[13px] leading-6 text-ds-ink">
              {selected.prompt}
            </p>
            <dl className="mt-5 grid grid-cols-2 gap-3 border-y border-ds-border-muted py-4 text-[12px]">
              <div>
                <dt className="text-ds-faint">{t('automationColNextRun')}</dt>
                <dd className="mt-1 text-ds-ink">
                  {formatAutomationWhen(selected.next_run_at)}
                </dd>
              </div>
              <div>
                <dt className="text-ds-faint">{t('automationLastRun')}</dt>
                <dd className="mt-1 text-ds-ink">
                  {formatAutomationWhen(selected.last_run_at)}
                </dd>
              </div>
              <div className="col-span-2">
                <dt className="text-ds-faint">{t('automationColDelivery')}</dt>
                <dd className="mt-1 text-ds-ink">{automationDeliveryDetail(selected, t)}</dd>
              </div>
            </dl>
            <div className="mt-5 flex items-center justify-between">
              <h3 className="text-[13px] font-semibold text-ds-ink">
                {t('automationRunHistory')}
              </h3>
              <button
                title={t('automationRefreshRuns')}
                onClick={() => void refreshRuns(selected.id)}
                className="rounded-md p-1.5 text-ds-muted hover:bg-ds-hover"
              >
                <RefreshCw className={`h-4 w-4 ${runsLoading ? 'animate-spin' : ''}`} />
              </button>
            </div>
            <div className="mt-2 divide-y divide-ds-border-muted border-y border-ds-border-muted">
              {runsLoading && runs.length === 0 ? (
                <div className="py-8 text-center text-[12px] text-ds-muted">
                  {t('automationLoading')}
                </div>
              ) : runs.length === 0 ? (
                <div className="py-8 text-center text-[12px] text-ds-muted">
                  {t('automationNoRuns')}
                </div>
              ) : (
                runs.map((run) => (
                  <div key={run.id} className="py-3 text-[12px]">
                    <div className="flex items-center justify-between gap-3">
                      <span className={`font-semibold ${runTone(run.status)}`}>
                        {run.status}
                      </span>
                      <span className="text-ds-faint">
                        {formatAutomationWhen(run.created_at)}
                      </span>
                    </div>
                    <dl className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-1 text-ds-muted">
                      <div>
                        {t('automationRunScheduled')}：
                        {formatAutomationWhen(run.scheduled_for)}
                      </div>
                      {run.started_at && (
                        <div>
                          {t('automationRunStartedAt')}：
                          {formatAutomationWhen(run.started_at)}
                        </div>
                      )}
                      {run.ended_at && (
                        <div>
                          {t('automationRunEndedAt')}：
                          {formatAutomationWhen(run.ended_at)}
                        </div>
                      )}
                      <div>
                        {t('automationColDelivery')}：
                        {formatRunDeliveryStatus(run, selected, t)}
                      </div>
                    </dl>
                    {run.task_id && (
                      <div className="mt-1 truncate font-mono text-[11px] text-ds-faint">
                        Task {run.task_id}
                        {run.thread_id ? ` · Thread ${run.thread_id}` : ''}
                        {run.turn_id ? ` · Turn ${run.turn_id}` : ''}
                      </div>
                    )}
                    {run.error && (
                      <div className="mt-2 rounded bg-red-500/10 px-2 py-1.5 text-red-700 dark:text-red-200">
                        {run.error}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
          </div>
        </>,
        document.body
      )
        : null}
    </div>
  )
}

import { getDataInventorySnapshot, loadDataInventory, type DataInventory, type StorageCategory } from '../../lib/data-inventory-cache'
import './data-storage.css'
import { GlobalErrorNotice } from '../GlobalFeedback'
import { ConfirmDialog } from '../workspace-editor/ConfirmDialog'
import { formatRuntimeError, getRuntimeErrorCode } from '../../lib/format-runtime-error'
import { useCallback, useEffect, useMemo, useState, type ReactElement, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { FolderOpen, Loader2, Settings2, Trash2 } from 'lucide-react'
import { useChatStore } from '../../store/chat-store'
import { SettingsSelect } from './SettingsSelect'
import {
  settingsBlockButtonClass,
  settingsToolbarButtonClass
} from './SettingsActionToolbar'
import { confirmAsync } from '../../lib/confirm-dialog'

type ActionState = 'idle' | 'running' | 'done' | 'error'
type ExportScope = 'conversations' | 'settings' | 'all'
type BackupMeta = {
  directory: string | null
  last_backup_at: string | null
  last_backup_path: string | null
}
type InlineNotice = {
  tone: 'success' | 'error' | 'info'
  message: string
}
type ImportPlan = {
  path: string
  has_conversations: boolean
  threads: number
  settings: string[]
}

/** Expected refusals get a localized explanation; anything else shows the runtime's reason. */
const DATA_ERROR_KEYS: Record<string, string> = {
  history_blocked: 'dataErrorHistoryBlocked',
  thread_active: 'dataErrorThreadActive',
  invalid_bundle: 'dataErrorInvalidBundle'
}

const CLEAN_AGE_OPTIONS = [
  { value: 30, labelKey: 'dataCleanAge30d' },
  { value: 90, labelKey: 'dataCleanAge90d' },
  { value: 180, labelKey: 'dataCleanAge180d' },
  { value: 365, labelKey: 'dataCleanAge365d' }
] as const

const EXPORT_SCOPE_OPTIONS = [
  { value: 'conversations', labelKey: 'dataExportScopeConversations' },
  { value: 'settings', labelKey: 'dataExportScopeSettings' },
  { value: 'all', labelKey: 'dataExportScopeAll' }
] as const

const CATEGORY_STYLE: Record<StorageCategory, { color: string; labelKey: string }> = {
  conversations: { color: 'violet', labelKey: 'dataCatConversations' },
  browser: { color: 'blue', labelKey: 'dataCatBrowser' },
  workspace: { color: 'teal', labelKey: 'dataCatWorkspace' },
  logs: { color: 'amber', labelKey: 'dataCatLogs' },
  worktrees: { color: 'orchid', labelKey: 'dataCatWorktrees' },
  other: { color: 'slate', labelKey: 'dataCatOther' }
}

function formatBytes(bytes: number, locale: string): string {
  const value = Math.max(0, Number(bytes) || 0)
  if (value < 1024) return `${value} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let size = value / 1024
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size.toLocaleString(locale, { maximumFractionDigits: 1 })} ${units[unit]}`
}

function formatCount(n: number, locale: string): string {
  return Math.max(0, Number(n) || 0).toLocaleString(locale)
}

function SettingsCard({
  title,
  children,
  className = ''
}: {
  title: string
  children: ReactNode
  className?: string
}): ReactElement {
  return (
    <section className={`ds-content-card rounded-2xl ${className}`}>
      <div className="border-b border-ds-border-muted px-5 py-3">
        <h2 className="text-[16px] font-semibold text-ds-ink">{title}</h2>
      </div>
      <div className="divide-y divide-ds-border-muted px-2 py-1">{children}</div>
    </section>
  )
}

function SettingRow({
  title,
  description,
  control,
  align = 'center'
}: {
  title: string
  description?: ReactNode
  control: ReactNode
  align?: 'center' | 'start'
}): ReactElement {
  return (
    <div
      className={[
        'ds-density-row flex flex-col gap-3 px-3 py-4 sm:flex-row sm:justify-between sm:gap-8',
        align === 'center' ? 'sm:items-center' : 'sm:items-start'
      ].join(' ')}
    >
      <div className="min-w-0 flex-1">
        <div className="text-[14px] font-semibold leading-none text-ds-ink">{title}</div>
        {description ? (
          typeof description === 'string' ? (
            <p className="mt-1.5 max-w-md text-pretty text-[13px] leading-relaxed text-ds-muted">
              {description}
            </p>
          ) : (
            <div className="mt-1.5 max-w-md text-[13px] leading-relaxed text-ds-muted">
              {description}
            </div>
          )
        ) : null}
      </div>
      <div className="flex w-full min-w-0 items-center justify-end sm:ml-auto sm:max-w-[168px] sm:shrink-0">
        {control}
      </div>
    </div>
  )
}

function ActionButton({
  children,
  onClick,
  disabled,
  busy,
  variant = 'default',
  block = false
}: {
  children: ReactNode
  onClick: () => void
  disabled?: boolean
  busy?: boolean
  variant?: 'default' | 'danger'
  block?: boolean
}): ReactElement {
  const dangerClass =
    'inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-red-300/80 bg-red-50 px-2.5 text-center text-[13px] font-medium leading-none text-red-700 shadow-sm transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-55 dark:border-red-800/70 dark:bg-red-950/30 dark:text-red-200 dark:hover:bg-red-950/45'
  const className =
    variant === 'danger'
      ? `${dangerClass}${block ? ' w-full' : ''}`
      : block
        ? settingsBlockButtonClass(Boolean(disabled || busy))
        : settingsToolbarButtonClass(Boolean(disabled || busy))
  return (
    <button type="button" disabled={disabled || busy} onClick={onClick} className={className}>
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.75} /> : null}
      {children}
    </button>
  )
}

function InlineNoticeView({ notice }: { notice: InlineNotice }): ReactElement {
  if (notice.tone === 'error') return <GlobalErrorNotice occurrence={notice} message={notice.message} />
  const className =
    notice.tone === 'success'
      ? 'border-emerald-300/80 bg-emerald-50 text-emerald-800 dark:border-emerald-800/70 dark:bg-emerald-950/25 dark:text-emerald-200'
      : 'border-ds-border bg-ds-main/50 text-ds-muted'
  return (
    <div className={`rounded-xl border px-3 py-2 text-[12.5px] leading-5 ${className}`}>
      {notice.message}
    </div>
  )
}

export function DataSettingsPanel(): ReactElement {
  const { t, i18n } = useTranslation('settings')
  const refreshThreads = useChatStore((s) => s.refreshThreads)
  const openSettings = useChatStore((s) => s.openSettings)
  const [inventory, setInventory] = useState<DataInventory | null>(() => getDataInventorySnapshot())
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loading, setLoading] = useState(() => !getDataInventorySnapshot())
  const [cleanAgeDays, setCleanAgeDays] = useState(90)
  const [exportScope, setExportScope] = useState<ExportScope>('conversations')
  const [backupMeta, setBackupMeta] = useState<BackupMeta | null>(null)
  const [optimizeState, setOptimizeState] = useState<ActionState>('idle')
  const [cleanState, setCleanState] = useState<ActionState>('idle')
  const [clearState, setClearState] = useState<ActionState>('idle')
  const [exportState, setExportState] = useState<ActionState>('idle')
  const [importState, setImportState] = useState<ActionState>('idle')
  const [importPlan, setImportPlan] = useState<ImportPlan | null>(null)
  const [backupState, setBackupState] = useState<ActionState>('idle')
  const [deleteExitState, setDeleteExitState] = useState<ActionState>('idle')
  const [notice, setNotice] = useState<InlineNotice | null>(null)
  const [openDirError, setOpenDirError] = useState<string | null>(null)

  const syncThreadList = useCallback(async (): Promise<void> => {
    try {
      await refreshThreads()
    } catch {
      // Disk ops already succeeded; sidebar lag is non-fatal.
    }
  }, [refreshThreads])

  const refreshBackup = useCallback(async (): Promise<void> => {
    try {
      const r = await window.dsGui.runtimeRequest('/v1/data/backup', 'GET')
      if (r.ok) setBackupMeta(JSON.parse(r.body) as BackupMeta)
    } catch {
      // optional
    }
  }, [])

  const refresh = useCallback(async (force = true): Promise<void> => {
    setLoading(!getDataInventorySnapshot())
    setLoadError(null)
    try {
      setInventory(await loadDataInventory(force))
      void refreshBackup()
    } catch {
      setLoadError(t('dataInventoryLoadFailed'))
    } finally {
      setLoading(false)
    }
  }, [refreshBackup, t])

  useEffect(() => {
    void refresh(false)
  }, [refresh])

  const composition = useMemo(() => {
    if (!inventory) return null
    const categories = inventory.categories ?? [
      { key: 'conversations' as const, bytes: inventory.total_bytes }
    ]
    const total = inventory.storage_total_bytes ?? inventory.total_bytes
    // Largest first, like system storage views; the catch-all stays last.
    const ordered = [...categories].sort((a, b) =>
      a.key === 'other' ? 1 : b.key === 'other' ? -1 : b.bytes - a.bytes
    )
    return {
      total,
      segments: ordered.map((c) => ({
        ...c,
        ...CATEGORY_STYLE[c.key],
        pct: Math.max(c.bytes > 0 ? 0.8 : 0, (c.bytes / (total || 1)) * 100)
      }))
    }
  }, [inventory])

  const lang = i18n.language

  const categoryDetail = (key: StorageCategory): string => {
    if (!inventory) return ''
    if (key === 'conversations') {
      const parts = [
        `${t('dataLegendEvents')} ${formatBytes(inventory.events_bytes, lang)}`,
        `${t('dataCheckpoints')} ${formatBytes(inventory.checkpoints_bytes, lang)}`
      ]
      if (inventory.sessions_bytes > 0) {
        parts.push(`${t('dataStatSessionsBytes')} ${formatBytes(inventory.sessions_bytes, lang)}`)
      }
      return parts.join(' · ')
    }
    if (key === 'logs') {
      const hours = inventory.log_keep_hours ?? 0
      if (hours <= 0) return t('dataCatLogsDescManual')
      const period =
        hours % 24 === 0
          ? t('dataPeriodDays', { count: hours / 24 })
          : t('dataPeriodHours', { count: hours })
      return t('dataCatLogsDesc', { period })
    }
    return t(`${CATEGORY_STYLE[key].labelKey}Desc`)
  }

  const revealPath = async (path: string): Promise<void> => {
    try {
      await window.dsGui.showItemInFolder(path)
    } catch (error) {
      showNotice('error', failure('dataOpenDirFailed', error))
    }
  }

  const categoryAction = (key: StorageCategory, bytes: number): ReactNode => {
    const category = inventory?.categories?.find((item) => item.key === key)
    // Older runtimes only expose the workspace, conversation, and home paths.
    const legacyPath = key === 'workspace' ? inventory?.workspace_dir
      : key === 'conversations' ? inventory?.threads_dir
        : key === 'other' ? inventory?.home_dir : undefined
    const path = category && 'reveal_path' in category
      ? category.reveal_path
      : bytes > 0 ? legacyPath : undefined
    const revealLabel = key === 'other' ? openDirLabel
      : t('dataReveal') + ' · ' + t(CATEGORY_STYLE[key].labelKey)
    return (
      <div className="flex shrink-0 items-center gap-1">
        {key === 'browser' ? (
          <button type="button" className="ds-data-storage__action" title={t('dataCatManage')}
            aria-label={t('dataCatManage')} onClick={() => openSettings('browser')}>
            <Settings2 size={16} strokeWidth={1.75} aria-hidden />
          </button>
        ) : null}
        {path ? (
          <button type="button" className="ds-data-storage__action" title={revealLabel}
            aria-label={revealLabel} onClick={() => void revealPath(path)}>
            <FolderOpen size={16} strokeWidth={1.75} aria-hidden />
          </button>
        ) : null}
      </div>
    )
  }

  const showNotice = (tone: InlineNotice['tone'], message: string): void => {
    setNotice({ tone, message })
  }

  const failure = (actionKey: string, reason?: unknown): string => {
    if (reason === undefined || reason === '') return t(actionKey)
    const known = DATA_ERROR_KEYS[getRuntimeErrorCode(reason) ?? '']
    if (known) return t(known)
    return t('dataFailedWithReason', { action: t(actionKey), reason: formatRuntimeError(reason) })
  }

  const runOptimize = async (): Promise<void> => {
    setOptimizeState('running')
    setNotice(null)
    try {
      const r = await window.dsGui.runtimeRequest('/v1/data/optimize', 'POST', '{}')
      if (!r.ok) {
        setOptimizeState('error')
        showNotice('error', failure('dataOptimizeFailed', r.body))
        return
      }
      const body = JSON.parse(r.body) as { bytes_reclaimed?: number }
      setOptimizeState('done')
      showNotice(
        'success',
        t('dataOptimizeDone', {
          bytes: formatBytes(body.bytes_reclaimed ?? 0, i18n.language)
        })
      )
      await refresh()
    } catch (error) {
      setOptimizeState('error')
      showNotice('error', failure('dataOptimizeFailed', error))
    }
  }

  const runClean = async (): Promise<void> => {
    setNotice(null)
    try {
      const preview = await window.dsGui.runtimeRequest(
        `/v1/data/clean/preview?older_than_days=${cleanAgeDays}`,
        'GET'
      )
      if (!preview.ok) {
        showNotice('error', failure('dataCleanFailed', preview.body))
        return
      }
      const matched = (JSON.parse(preview.body) as { threads_matched?: number }).threads_matched ?? 0
      if (matched === 0) {
        showNotice('info', t('dataCleanNone', { days: cleanAgeDays }))
        return
      }
      const message = t('dataCleanConfirm', { count: matched, days: cleanAgeDays })
      if (!(await confirmAsync(message, { destructive: true }))) return
      setCleanState('running')
      const r = await window.dsGui.runtimeRequest(
        '/v1/data/clean',
        'POST',
        JSON.stringify({ older_than_days: cleanAgeDays })
      )
      if (!r.ok) {
        setCleanState('error')
        showNotice('error', failure('dataCleanFailed', r.body))
        return
      }
      const body = JSON.parse(r.body) as { threads_deleted?: number; threads_skipped?: number }
      const count = body.threads_deleted ?? 0
      const skipped = body.threads_skipped ?? 0
      setCleanState('done')
      showNotice(
        'success',
        skipped > 0 ? t('dataCleanDoneSkipped', { count, skipped }) : t('dataCleanDone', { count })
      )
      await refresh()
      await syncThreadList()
    } catch (error) {
      setCleanState('error')
      showNotice('error', failure('dataCleanFailed', error))
    }
  }

  const runClearHistory = async (): Promise<void> => {
    if (!(await confirmAsync(t('dataClearHistoryConfirm'), { destructive: true }))) return
    if (!(await confirmAsync(t('dataClearHistoryConfirm2'), { destructive: true }))) return
    setClearState('running')
    setNotice(null)
    try {
      const r = await window.dsGui.runtimeRequest('/v1/data/clear-history', 'POST', '{}')
      if (!r.ok) {
        setClearState('error')
        showNotice('error', failure('dataClearHistoryFailed', r.body))
        return
      }
      setClearState('done')
      showNotice('success', t('dataClearHistoryDone'))
      await refresh()
      await syncThreadList()
    } catch (error) {
      setClearState('error')
      showNotice('error', failure('dataClearHistoryFailed', error))
    }
  }

  const openDataDir = async (): Promise<void> => {
    setOpenDirError(null)
    if (typeof window.dsGui?.openDeepseekHomeDir !== 'function') {
      setOpenDirError(t('dataOpenDirFailed'))
      return
    }
    const result = await window.dsGui.openDeepseekHomeDir()
    if (!result.ok) setOpenDirError(result.message || t('dataOpenDirFailed'))
  }

  const runExport = async (): Promise<void> => {
    if (typeof window.dsGui?.pickDataExportPath !== 'function') {
      showNotice('error', t('dataExportFailed'))
      return
    }
    if (
      (exportScope === 'all' || exportScope === 'settings') &&
      !(await confirmAsync(t('dataExportSecretsConfirm')))
    ) {
      return
    }
    const picked = await window.dsGui.pickDataExportPath()
    if (picked.canceled || !picked.path) return
    setExportState('running')
    setNotice(null)
    try {
      const r = await window.dsGui.runtimeRequest(
        '/v1/data/export',
        'POST',
        JSON.stringify({ path: picked.path, scope: exportScope })
      )
      if (!r.ok) {
        setExportState('error')
        showNotice('error', failure('dataExportFailed', r.body))
        return
      }
      const body = JSON.parse(r.body) as { path?: string }
      setExportState('done')
      showNotice('success', t('dataExportDone', { path: body.path ?? picked.path }))
    } catch (error) {
      setExportState('error')
      showNotice('error', failure('dataExportFailed', error))
    }
  }

  const runImport = async (): Promise<void> => {
    if (typeof window.dsGui?.pickDataImportPath !== 'function') {
      showNotice('error', t('dataImportFailed'))
      return
    }
    setNotice(null)
    try {
      const picked = await window.dsGui.pickDataImportPath()
      if (picked.canceled || !picked.path) return
      const r = await window.dsGui.runtimeRequest(
        '/v1/data/import/inspect',
        'POST',
        JSON.stringify({ path: picked.path })
      )
      if (!r.ok) {
        showNotice('error', failure('dataImportFailed', r.body))
        return
      }
      const plan = { ...(JSON.parse(r.body) as Omit<ImportPlan, 'path'>), path: picked.path }
      if (!plan.has_conversations && plan.settings.length === 0) {
        showNotice('info', t('dataImportEmpty'))
        return
      }
      setImportPlan(plan)
    } catch (error) {
      showNotice('error', failure('dataImportFailed', error))
    }
  }

  const confirmImport = async (mode: 'merge' | 'replace'): Promise<void> => {
    if (!importPlan || importState === 'running') return
    const plan = importPlan
    setImportPlan(null)
    if (
      mode === 'replace' &&
      plan.has_conversations &&
      !(await confirmAsync(t('dataImportReplaceConfirm', { count: plan.threads }), { destructive: true }))
    ) {
      return
    }
    const path = plan.path
    setImportState('running')
    setNotice(null)
    try {
      const r = await window.dsGui.runtimeRequest(
        '/v1/data/import',
        'POST',
        JSON.stringify({ path, mode })
      )
      if (!r.ok) {
        setImportState('error')
        showNotice('error', failure('dataImportFailed', r.body))
        return
      }
      const body = JSON.parse(r.body) as {
        threads_imported?: number
        threads_skipped?: number
        settings_restored?: string[]
      }
      const settingsRestored = Array.isArray(body.settings_restored) ? body.settings_restored : []
      const importSummary = t('dataImportDone', {
        imported: body.threads_imported ?? 0,
        skipped: body.threads_skipped ?? 0
      })
      setImportState('done')
      showNotice(
        'success',
        !plan.has_conversations
          ? t('dataImportSettingsRestartHint')
          : settingsRestored.length > 0
            ? `${importSummary} ${t('dataImportSettingsRestartHint')}`
            : importSummary
      )
      await refresh()
      await syncThreadList()
    } catch (error) {
      setImportState('error')
      showNotice('error', failure('dataImportFailed', error))
    }
  }

  const pickBackupDir = async (): Promise<void> => {
    if (typeof window.dsGui?.pickBackupDirectory !== 'function') return
    try {
      const picked = await window.dsGui.pickBackupDirectory()
      if (picked.canceled || !picked.path) return
      const r = await window.dsGui.runtimeRequest(
        '/v1/data/backup/directory',
        'POST',
        JSON.stringify({ directory: picked.path })
      )
      if (!r.ok) {
        showNotice('error', failure('dataBackupDirFailed', r.body))
        return
      }
      setBackupMeta(JSON.parse(r.body) as BackupMeta)
      showNotice('success', t('dataBackupDirSet'))
    } catch (error) {
      showNotice('error', failure('dataBackupDirFailed', error))
    }
  }

  const runBackupNow = async (): Promise<void> => {
    setBackupState('running')
    setNotice(null)
    try {
      const r = await window.dsGui.runtimeRequest('/v1/data/backup', 'POST', '{}')
      if (!r.ok) {
        setBackupState('error')
        showNotice('error', failure('dataBackupFailed', r.body))
        return
      }
      const body = JSON.parse(r.body) as BackupMeta & { path?: string }
      setBackupMeta({
        directory: body.directory ?? backupMeta?.directory ?? null,
        last_backup_at: body.last_backup_at ?? null,
        last_backup_path: body.path ?? body.last_backup_path ?? null
      })
      setBackupState('done')
      showNotice('success', t('dataBackupDone', { path: body.path ?? '' }))
    } catch (error) {
      setBackupState('error')
      showNotice('error', failure('dataBackupFailed', error))
    }
  }

  const runDeleteAndExit = async (): Promise<void> => {
    if (!(await confirmAsync(t('dataDeleteAndExitConfirm'), { destructive: true }))) return
    if (!(await confirmAsync(t('dataDeleteAndExitConfirm2'), { destructive: true }))) return
    setDeleteExitState('running')
    try {
      const result = await window.dsGui.deleteGuiDataAndExit()
      if (!result.ok) {
        setDeleteExitState('error')
        showNotice('error', result.message || t('dataDeleteAndExitFailed'))
      }
    } catch {
      setDeleteExitState('error')
      showNotice('error', t('dataDeleteAndExitFailed'))
    }
  }

  const formatBackupTime = (iso: string | null | undefined): string => {
    if (!iso) return t('dataBackupNever')
    try {
      return new Date(iso).toLocaleString(i18n.language)
    } catch {
      return iso
    }
  }

  const busy =
    optimizeState === 'running' ||
    cleanState === 'running' ||
    clearState === 'running' ||
    exportState === 'running' ||
    importState === 'running' ||
    backupState === 'running' ||
    deleteExitState === 'running'

  const openDirLabel =
    window.dsGui?.platform === 'darwin'
      ? t('dataOpenDirectoryMac')
      : window.dsGui?.platform === 'win32'
        ? t('dataOpenDirectoryWin')
        : t('dataOpenDirectory')

  return (
    <>
      {importPlan?.has_conversations ? (
        <ConfirmDialog
          title={t('dataImportChooseTitle')}
          body={t(importPlan.settings.length > 0 ? 'dataImportChooseBodyWithSettings' : 'dataImportChooseBody', {
            count: importPlan.threads
          })}
          confirmLabel={t('dataImportMerge')}
          cancelLabel={t('cancel')}
          secondaryAction={{ label: t('dataImportReplace'), onClick: () => void confirmImport('replace') }}
          onConfirm={() => void confirmImport('merge')}
          onCancel={() => setImportPlan(null)}
        />
      ) : importPlan ? (
        <ConfirmDialog
          title={t('dataImportSettingsTitle')}
          body={t('dataImportSettingsBody', { files: new Intl.ListFormat(i18n.language).format(importPlan.settings) })}
          destructive
          confirmLabel={t('dataImportSettingsAction')}
          cancelLabel={t('cancel')}
          onConfirm={() => void confirmImport('replace')}
          onCancel={() => setImportPlan(null)}
        />
      ) : null}
    <div className="flex flex-col gap-6">
      {notice ? <InlineNoticeView notice={notice} /> : null}

      <SettingsCard title={t('dataStorageSection')}>
        {loading ? (
          <div className="flex items-center gap-2 px-3 py-6 text-[13px] text-ds-muted">
            <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.75} />
            {t('dataInventoryLoading')}
          </div>
        ) : loadError && !inventory ? (
          <div className="px-3 py-4 text-[13px] text-red-700 dark:text-red-300">{loadError}</div>
        ) : inventory && composition ? (
          <>
            <div className="ds-data-storage px-3 py-4">
              {loadError ? <p role="status" className="mb-3 text-[12px] text-ds-muted">{loadError}</p> : null}
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <div className="text-[12.5px] font-medium text-ds-faint">{t('dataTotalUsed')}</div>
                  <div className="mt-1 text-[28px] font-semibold tracking-tight tabular-nums text-ds-ink">
                    {formatBytes(composition.total, i18n.language)}
                  </div>
                </div>
                <div className="text-[13px] text-ds-muted">
                  {formatCount(inventory.thread_count, i18n.language)} {t('dataStatThreadCount')}
                  <span className="mx-2 text-ds-faint">·</span>
                  {formatCount(inventory.message_count, i18n.language)} {t('dataStatMessageCount')}
                </div>
              </div>
              <div className="ds-data-storage__bar mt-4">
                {composition.segments.map((seg) =>
                  seg.bytes > 0 ? (
                    <div
                      key={seg.key}
                      className="ds-data-storage__segment"
                      data-storage-tone={seg.color}
                      style={{ flexGrow: seg.pct, flexBasis: 0 }}
                    />
                  ) : null
                )}
              </div>
              <ul className="ds-data-storage__list mt-4">
                {composition.segments.map((seg) => (
                  <li key={seg.key} className="ds-data-storage__stat" data-storage-tone={seg.color}>
                    <span aria-hidden className="ds-data-storage__dot" />
                    <div className="min-w-0 flex-1">
                      <div className="text-[13.5px] font-medium leading-5 text-ds-ink">{t(seg.labelKey)}</div>
                      <div className="truncate text-[12.5px] leading-5 text-ds-muted">
                        {categoryDetail(seg.key)}
                      </div>
                    </div>
                    {categoryAction(seg.key, seg.bytes)}
                    <div className="ds-data-storage__value">
                      {formatBytes(seg.bytes, i18n.language)}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
            <SettingRow
              title={t('dataDirectory')}
              description={
                <div className="space-y-1">
                  <p>{t('dataDirectoryDesc')}</p>
                  {openDirError ? (
                    <p className="text-[12px] text-red-700 dark:text-red-300">{openDirError}</p>
                  ) : null}
                </div>
              }
              control={
                <button type="button" className="ds-data-storage__action" disabled={busy}
                  title={openDirLabel} aria-label={openDirLabel} onClick={() => void openDataDir()}>
                  <FolderOpen size={16} strokeWidth={1.75} aria-hidden />
                </button>
              }
            />
          </>
        ) : null}
      </SettingsCard>

      <SettingsCard title={t('dataMigrationSection')}>
        <SettingRow
          title={t('dataExport')}
          description={t('dataExportDesc')}
          align="start"
          control={
            <div className="flex w-full flex-col gap-2">
              <SettingsSelect
                value={exportScope}
                onChange={(e) => setExportScope(e.target.value as ExportScope)}
                disabled={busy}
              >
                {EXPORT_SCOPE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {t(opt.labelKey)}
                  </option>
                ))}
              </SettingsSelect>
              <ActionButton
                block
                busy={exportState === 'running'}
                disabled={busy}
                onClick={() => void runExport()}
              >
                {t('dataExportAction')}
              </ActionButton>
            </div>
          }
        />
        <SettingRow
          title={t('dataImport')}
          description={t('dataImportDesc')}
          control={
            <ActionButton
              block
              busy={importState === 'running'}
              disabled={busy}
              onClick={() => void runImport()}
            >
              {t('dataImportAction')}
            </ActionButton>
          }
        />
        <div className="px-3 py-3 text-[12.5px] leading-5 text-ds-faint">{t('dataMigrationFooter')}</div>
      </SettingsCard>

      <SettingsCard title={t('dataBackupSection')}>
        <SettingRow
          title={t('dataBackupDirectory')}
          description={
            backupMeta?.directory ? (
              <code className="block truncate rounded-lg bg-ds-main/70 px-2 py-1 font-mono text-[12px] text-ds-ink">
                {backupMeta.directory}
              </code>
            ) : (
              t('dataBackupDirectoryUnset')
            )
          }
          control={
            <ActionButton block disabled={busy} onClick={() => void pickBackupDir()}>
              <FolderOpen className="h-4 w-4" strokeWidth={1.75} />
              {t('dataBackupChooseDir')}
            </ActionButton>
          }
        />
        <SettingRow
          title={t('dataBackupLast')}
          description={
            backupMeta?.last_backup_at && backupMeta.last_backup_path ? (
              <span className="inline-flex flex-wrap items-center gap-x-2">
                {formatBackupTime(backupMeta.last_backup_at)}
                <button
                  type="button"
                  className="font-medium text-accent hover:underline"
                  onClick={() => void revealPath(backupMeta.last_backup_path as string)}
                >
                  {openDirLabel}
                </button>
              </span>
            ) : (
              formatBackupTime(backupMeta?.last_backup_at)
            )
          }
          control={
            <ActionButton
              block
              busy={backupState === 'running'}
              disabled={busy || !backupMeta?.directory}
              onClick={() => void runBackupNow()}
            >
              {t('dataBackupNow')}
            </ActionButton>
          }
        />
        <div className="px-3 py-3 text-[12.5px] leading-5 text-ds-faint">{t('dataBackupFooter')}</div>
      </SettingsCard>

      <SettingsCard title={t('dataMaintenanceSection')}>
        <SettingRow
          title={t('dataOptimize')}
          description={t('dataOptimizeDesc')}
          control={
            <ActionButton
              block
              busy={optimizeState === 'running'}
              disabled={busy}
              onClick={() => void runOptimize()}
            >
              {t('dataOptimizeAction')}
            </ActionButton>
          }
        />
        <SettingRow
          title={t('dataCleanByAge')}
          description={t('dataCleanByAgeDesc')}
          align="start"
          control={
            <div className="flex w-full flex-col gap-2">
              <SettingsSelect
                value={String(cleanAgeDays)}
                onChange={(e) => setCleanAgeDays(Number(e.target.value))}
                disabled={busy}
              >
                {CLEAN_AGE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {t(opt.labelKey)}
                  </option>
                ))}
              </SettingsSelect>
              <ActionButton
                block
                busy={cleanState === 'running'}
                disabled={busy}
                onClick={() => void runClean()}
              >
                {t('dataCleanAction')}
              </ActionButton>
            </div>
          }
        />
        <div className="px-3 py-3 text-[12.5px] leading-5 text-ds-faint">{t('dataMaintenanceFooter')}</div>
      </SettingsCard>

      <SettingsCard title={t('dataLocalResetSection')}>
        <SettingRow
          title={t('dataClearHistory')}
          description={t('dataClearHistoryDesc')}
          control={
            <ActionButton
              block
              variant="danger"
              busy={clearState === 'running'}
              disabled={busy}
              onClick={() => void runClearHistory()}
            >
              <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />
              {t('dataClearHistoryAction')}
            </ActionButton>
          }
        />
        <SettingRow
          title={t('dataDeleteAndExit')}
          description={t('dataDeleteAndExitDesc')}
          control={
            <ActionButton
              block
              variant="danger"
              busy={deleteExitState === 'running'}
              disabled={busy}
              onClick={() => void runDeleteAndExit()}
            >
              <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />
              {t('dataDeleteAndExitAction')}
            </ActionButton>
          }
        />
      </SettingsCard>
    </div>
    </>
  )
}

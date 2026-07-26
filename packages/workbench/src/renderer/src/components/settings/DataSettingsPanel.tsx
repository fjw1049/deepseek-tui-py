import { useCallback, useEffect, useMemo, useState, type ReactElement, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { FolderOpen, Loader2, Trash2 } from 'lucide-react'
import { SettingsSelect } from './SettingsSelect'
import {
  settingsBlockButtonClass,
  settingsToolbarButtonClass
} from './SettingsActionToolbar'

type DataInventory = {
  home_dir: string
  threads_dir: string
  sessions_dir: string
  state_db_path: string
  threads_bytes: number
  sessions_bytes: number
  state_db_bytes: number
  events_bytes: number
  checkpoints_bytes: number
  thread_count: number
  message_count: number
  item_count: number
  total_bytes: number
}

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

const COMPOSITION_COLORS = {
  conversations: 'bg-[#5ac8fa] dark:bg-[#64d2ff]',
  events: 'bg-accent',
  sessions: 'bg-[#af52de] dark:bg-[#bf5af2]',
  other: 'bg-ds-faint'
} as const

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
  const className =
    notice.tone === 'error'
      ? 'border-red-300/80 bg-red-50 text-red-800 dark:border-red-800/70 dark:bg-red-950/25 dark:text-red-200'
      : notice.tone === 'success'
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
  const [inventory, setInventory] = useState<DataInventory | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [cleanAgeDays, setCleanAgeDays] = useState(90)
  const [exportScope, setExportScope] = useState<ExportScope>('conversations')
  const [backupMeta, setBackupMeta] = useState<BackupMeta | null>(null)
  const [optimizeState, setOptimizeState] = useState<ActionState>('idle')
  const [cleanState, setCleanState] = useState<ActionState>('idle')
  const [clearState, setClearState] = useState<ActionState>('idle')
  const [exportState, setExportState] = useState<ActionState>('idle')
  const [importState, setImportState] = useState<ActionState>('idle')
  const [backupState, setBackupState] = useState<ActionState>('idle')
  const [deleteExitState, setDeleteExitState] = useState<ActionState>('idle')
  const [notice, setNotice] = useState<InlineNotice | null>(null)
  const [openDirError, setOpenDirError] = useState<string | null>(null)

  const refreshBackup = useCallback(async (): Promise<void> => {
    try {
      const r = await window.dsGui.runtimeRequest('/v1/data/backup', 'GET')
      if (r.ok) setBackupMeta(JSON.parse(r.body) as BackupMeta)
    } catch {
      // optional
    }
  }, [])

  const refresh = useCallback(async (): Promise<void> => {
    setLoading(true)
    setLoadError(null)
    try {
      const r = await window.dsGui.runtimeRequest('/v1/data/inventory', 'GET')
      if (!r.ok) {
        setLoadError(t('dataInventoryLoadFailed'))
        setInventory(null)
        return
      }
      setInventory(JSON.parse(r.body) as DataInventory)
      await refreshBackup()
    } catch {
      setLoadError(t('dataInventoryLoadFailed'))
      setInventory(null)
    } finally {
      setLoading(false)
    }
  }, [refreshBackup, t])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const composition = useMemo(() => {
    if (!inventory) return null
    const conversationCore = Math.max(
      0,
      inventory.threads_bytes - inventory.events_bytes - inventory.checkpoints_bytes
    )
    const segments = [
      { key: 'conversations', bytes: conversationCore, color: COMPOSITION_COLORS.conversations },
      { key: 'events', bytes: inventory.events_bytes, color: COMPOSITION_COLORS.events },
      { key: 'sessions', bytes: inventory.sessions_bytes, color: COMPOSITION_COLORS.sessions },
      {
        key: 'other',
        bytes: inventory.checkpoints_bytes + inventory.state_db_bytes,
        color: COMPOSITION_COLORS.other
      }
    ] as const
    const total = segments.reduce((sum, s) => sum + s.bytes, 0) || 1
    return {
      total: inventory.total_bytes,
      segments: segments.map((s) => ({
        ...s,
        pct: Math.max(s.bytes > 0 ? 0.8 : 0, (s.bytes / total) * 100)
      }))
    }
  }, [inventory])

  const showNotice = (tone: InlineNotice['tone'], message: string): void => {
    setNotice({ tone, message })
  }

  const runOptimize = async (): Promise<void> => {
    setOptimizeState('running')
    setNotice(null)
    try {
      const r = await window.dsGui.runtimeRequest('/v1/data/optimize', 'POST', '{}')
      if (!r.ok) {
        setOptimizeState('error')
        showNotice('error', t('dataOptimizeFailed'))
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
    } catch {
      setOptimizeState('error')
      showNotice('error', t('dataOptimizeFailed'))
    }
  }

  const runClean = async (): Promise<void> => {
    if (!window.confirm(t('dataCleanConfirm', { days: cleanAgeDays }))) return
    setCleanState('running')
    setNotice(null)
    try {
      const r = await window.dsGui.runtimeRequest(
        '/v1/data/clean',
        'POST',
        JSON.stringify({ older_than_days: cleanAgeDays })
      )
      if (!r.ok) {
        setCleanState('error')
        showNotice('error', t('dataCleanFailed'))
        return
      }
      const body = JSON.parse(r.body) as { threads_deleted?: number }
      setCleanState('done')
      showNotice('success', t('dataCleanDone', { count: body.threads_deleted ?? 0 }))
      await refresh()
    } catch {
      setCleanState('error')
      showNotice('error', t('dataCleanFailed'))
    }
  }

  const runClearHistory = async (): Promise<void> => {
    if (!window.confirm(t('dataClearHistoryConfirm'))) return
    if (!window.confirm(t('dataClearHistoryConfirm2'))) return
    setClearState('running')
    setNotice(null)
    try {
      const r = await window.dsGui.runtimeRequest('/v1/data/clear-history', 'POST', '{}')
      if (!r.ok) {
        setClearState('error')
        showNotice('error', t('dataClearHistoryFailed'))
        return
      }
      setClearState('done')
      showNotice('success', t('dataClearHistoryDone'))
      await refresh()
    } catch {
      setClearState('error')
      showNotice('error', t('dataClearHistoryFailed'))
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
      !window.confirm(t('dataExportSecretsConfirm'))
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
        showNotice('error', t('dataExportFailed'))
        return
      }
      const body = JSON.parse(r.body) as { path?: string }
      setExportState('done')
      showNotice('success', t('dataExportDone', { path: body.path ?? picked.path }))
    } catch {
      setExportState('error')
      showNotice('error', t('dataExportFailed'))
    }
  }

  const runImport = async (): Promise<void> => {
    if (typeof window.dsGui?.pickDataImportPath !== 'function') {
      showNotice('error', t('dataImportFailed'))
      return
    }
    const picked = await window.dsGui.pickDataImportPath()
    if (picked.canceled || !picked.path) return
    const mode = window.confirm(t('dataImportModeConfirm')) ? 'replace' : 'merge'
    setImportState('running')
    setNotice(null)
    try {
      const r = await window.dsGui.runtimeRequest(
        '/v1/data/import',
        'POST',
        JSON.stringify({ path: picked.path, mode })
      )
      if (!r.ok) {
        setImportState('error')
        showNotice('error', t('dataImportFailed'))
        return
      }
      const body = JSON.parse(r.body) as { threads_imported?: number; threads_skipped?: number }
      setImportState('done')
      showNotice(
        'success',
        t('dataImportDone', {
          imported: body.threads_imported ?? 0,
          skipped: body.threads_skipped ?? 0
        })
      )
      await refresh()
    } catch {
      setImportState('error')
      showNotice('error', t('dataImportFailed'))
    }
  }

  const pickBackupDir = async (): Promise<void> => {
    if (typeof window.dsGui?.pickBackupDirectory !== 'function') return
    const picked = await window.dsGui.pickBackupDirectory()
    if (picked.canceled || !picked.path) return
    const r = await window.dsGui.runtimeRequest(
      '/v1/data/backup/directory',
      'POST',
      JSON.stringify({ directory: picked.path })
    )
    if (!r.ok) {
      showNotice('error', t('dataBackupDirFailed'))
      return
    }
    setBackupMeta(JSON.parse(r.body) as BackupMeta)
    showNotice('success', t('dataBackupDirSet'))
  }

  const runBackupNow = async (): Promise<void> => {
    setBackupState('running')
    setNotice(null)
    try {
      const r = await window.dsGui.runtimeRequest('/v1/data/backup', 'POST', '{}')
      if (!r.ok) {
        setBackupState('error')
        showNotice('error', t('dataBackupFailed'))
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
    } catch {
      setBackupState('error')
      showNotice('error', t('dataBackupFailed'))
    }
  }

  const runDeleteAndExit = async (): Promise<void> => {
    if (!window.confirm(t('dataDeleteAndExitConfirm'))) return
    if (!window.confirm(t('dataDeleteAndExitConfirm2'))) return
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
    <div className="flex flex-col gap-6">
      {notice ? <InlineNoticeView notice={notice} /> : null}

      <SettingsCard title={t('dataStorageSection')}>
        {loading ? (
          <div className="flex items-center gap-2 px-3 py-6 text-[13px] text-ds-muted">
            <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.75} />
            {t('dataInventoryLoading')}
          </div>
        ) : loadError ? (
          <div className="px-3 py-4 text-[13px] text-red-700 dark:text-red-300">{loadError}</div>
        ) : inventory && composition ? (
          <>
            <div className="px-3 py-4">
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
              <div className="mt-4 flex h-3 overflow-hidden rounded-full bg-ds-subtle">
                {composition.segments.map((seg) =>
                  seg.bytes > 0 ? (
                    <div
                      key={seg.key}
                      className={`${seg.color} min-w-[2px]`}
                      style={{ flexGrow: seg.pct, flexBasis: 0 }}
                    />
                  ) : null
                )}
              </div>
              <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <StatTile
                  label={t('dataStatThreadsBytes')}
                  value={formatBytes(
                    Math.max(
                      0,
                      inventory.threads_bytes - inventory.events_bytes - inventory.checkpoints_bytes
                    ),
                    i18n.language
                  )}
                />
                <StatTile
                  label={t('dataLegendEvents')}
                  value={formatBytes(inventory.events_bytes, i18n.language)}
                />
                <StatTile
                  label={t('dataStatSessionsBytes')}
                  value={formatBytes(inventory.sessions_bytes, i18n.language)}
                />
                <StatTile
                  label={t('dataLegendOther')}
                  value={formatBytes(
                    inventory.checkpoints_bytes + inventory.state_db_bytes,
                    i18n.language
                  )}
                />
              </div>
              <p className="mt-3 text-[12.5px] leading-5 text-ds-faint">{t('dataStorageFooter')}</p>
            </div>
            <SettingRow
              title={t('dataDirectory')}
              description={
                <div className="space-y-1">
                  <p>{t('dataDirectoryDesc')}</p>
                  <code className="block truncate rounded-lg bg-ds-main/70 px-2 py-1 font-mono text-[12px] text-ds-ink">
                    {inventory.home_dir}
                  </code>
                  {openDirError ? (
                    <p className="text-[12px] text-red-700 dark:text-red-300">{openDirError}</p>
                  ) : null}
                </div>
              }
              control={
                <ActionButton block disabled={busy} onClick={() => void openDataDir()}>
                  <FolderOpen className="h-4 w-4" strokeWidth={1.75} />
                  {openDirLabel}
                </ActionButton>
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
          description={formatBackupTime(backupMeta?.last_backup_at)}
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
        <div className="px-3 py-3 text-[12.5px] leading-5 text-ds-faint">{t('dataDeleteAndExitFooter')}</div>
      </SettingsCard>
    </div>
  )
}

function StatTile({ label, value }: { label: string; value: string }): ReactElement {
  return (
    <div className="rounded-xl border border-ds-border-muted bg-ds-card/60 px-3 py-2.5">
      <div className="text-[11.5px] font-medium text-ds-faint">{label}</div>
      <div className="mt-1 text-[14px] font-semibold tabular-nums text-ds-ink">{value}</div>
    </div>
  )
}

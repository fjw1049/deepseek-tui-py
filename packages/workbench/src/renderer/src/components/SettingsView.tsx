import { SettingsToggle as Toggle } from './settings/SettingsToggle'
import { cacheSettingsSnapshot, getSettingsSnapshot, loadSettingsSnapshot } from '../lib/settings-snapshot'
import { GlobalErrorNotice } from './GlobalFeedback'
import { ConfirmDialog } from './workspace-editor/ConfirmDialog'
import { formatRuntimeError } from '../lib/format-runtime-error'
import type { ReactElement, ReactNode } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  mergeAppearanceSettings,
  mergeClawSettings,
  mergeLlmProviders,
  mergeShortcutsSettings,
  mergeWebSearchSettings,
  sandboxModeForApprovalPolicy,
  type AppearancePatchV1,
  type ApprovalPolicy,
  type AppSettingsV1,
  type BuiltinLlmProviderId,
  type ClawSettingsPatchV1,
  type LlmProviderConfigV1,
  type ShortcutsPatchV1,
  type WebSearchSettingsPatchV1
} from '@shared/app-settings'
import {
  SHORTCUT_CATALOG,
  formatShortcutLabel,
  shortcutChordTokens,
  type ShortcutChord
} from '@shared/shortcuts'
import {
  ChevronDown,
  Eye,
  EyeOff,
  FolderOpen,
  Loader2
} from 'lucide-react'
import { applyTheme, applyUiFontScale, applyUiFontFamily } from '../lib/apply-theme'
import { applyAppearance } from '../lib/apply-appearance'
import { applyShortcutsSettings } from '../lib/shortcuts-runtime'
import { formatWorkspacePickerError } from '../lib/format-workspace-picker-error'
import {
  readPetAiLines,
  readPetChatter,
  readPetEnabled,
  readPetSlug,
  subscribePetPreferences,
  writePetAiLines,
  writePetChatter,
  writePetEnabled,
  writePetSlug
} from '../lib/pet/pet-preferences'
import {
  BUNDLED_POPULAR_PETS,
  type PetPopularEntry
} from '@shared/pet-popular'
import { DEFAULT_WORKSPACE_ROOT } from '@shared/workspace-defaults'
import { normalizeWorkspaceRoot } from '../lib/workspace-path'
import { useChatStore, type SettingsRouteSection } from '../store/chat-store'
import { setSettingsLeaveHandler } from '../lib/settings-leave'
import { DefaultEditorPicker } from './DefaultEditorPicker'
import { InitialSetupPanel } from './InitialSetupDialog'
import { AppearanceSettingsPanel } from './settings/AppearanceSettingsPanel'
import { ArchiveSettingsPanel } from './settings/ArchiveSettingsPanel'
import { NetworkSettingsPanel } from './settings/NetworkSettingsPanel'
import { WebSearchSettingsPanel } from './settings/WebSearchSettingsPanel'
import { SessionImportPanel } from './settings/SessionImportPanel'
import { DataSettingsPanel } from './settings/DataSettingsPanel'
import { SharingSettingsPanel } from './settings/SharingSettingsPanel'
import { BrowserSettingsPanel } from './settings/BrowserSettingsPanel'
import { CuaSettingsPanel } from './settings/CuaSettingsPanel'
import { LlmProvidersPanel } from './settings/LlmProvidersPanel'
import { ModelUsagePanel } from './settings/ModelUsagePanel'
import { settingsBlockButtonClass } from './settings/SettingsActionToolbar'
import { SettingsSelect } from './settings/SettingsSelect'
import { PetPicker, type PetPickerItem } from './pet/PetPicker'
import { FieldHelpPopover } from './channels/FieldHelpPopover'
import type { UsageRange } from '@shared/usage-ledger'
import { usePersistentUsage } from '../hooks/use-persistent-usage'

type SettingsCategory = SettingsRouteSection
type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'
type SettingsPatch = Partial<
  Omit<
    AppSettingsV1,
    | 'deepseek'
    | 'log'
    | 'notifications'
    | 'skills'
    | 'memory'
    | 'claw'
    | 'guiUpdate'
    | 'customEndpoints'
    | 'asrProviders'
    | 'llmProviders'
    | 'webSearch'
    | 'appearance'
    | 'shortcuts'
  >
> & {
  deepseek?: Partial<AppSettingsV1['deepseek']>
  log?: Partial<AppSettingsV1['log']>
  notifications?: Partial<AppSettingsV1['notifications']>
  skills?: Partial<AppSettingsV1['skills']>
  claw?: ClawSettingsPatchV1
  guiUpdate?: Partial<AppSettingsV1['guiUpdate']>
  customEndpoints?: AppSettingsV1['customEndpoints']
  asrProviders?: AppSettingsV1['asrProviders']
  llmProviders?: Partial<Record<BuiltinLlmProviderId, Partial<LlmProviderConfigV1>>>
  webSearch?: WebSearchSettingsPatchV1
  appearance?: AppearancePatchV1
  shortcuts?: ShortcutsPatchV1
}
type InlineNotice = {
  tone: 'success' | 'error' | 'info'
  message: string
}

function splitSettingsList(raw: string): string[] {
  return raw
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function listSettingsText(values: string[]): string {
  return values.join('\n')
}

function hasValidPort(settings: AppSettingsV1): boolean {
  const port = settings.deepseek.port
  return Number.isFinite(port) && port >= 1 && port <= 65535
}

function mergeSettings(current: AppSettingsV1, patch: SettingsPatch): AppSettingsV1 {
  return {
    ...current,
    ...patch,
    deepseek: {
      ...current.deepseek,
      ...(patch.deepseek ?? {})
    },
    llmProviders: mergeLlmProviders(current.llmProviders, patch.llmProviders),
    customEndpoints: patch.customEndpoints ?? current.customEndpoints,
    asrProviders: patch.asrProviders ?? current.asrProviders,
    webSearch: mergeWebSearchSettings(current.webSearch, patch.webSearch),
    log: {
      ...current.log,
      ...(patch.log ?? {})
    },
    notifications: {
      ...current.notifications,
      ...(patch.notifications ?? {})
    },
    skills: {
      ...current.skills,
      ...(patch.skills ?? {})
    },
    claw: mergeClawSettings(current.claw, patch.claw),
    guiUpdate: {
      ...current.guiUpdate,
      ...(patch.guiUpdate ?? {})
    },
    appearance: mergeAppearanceSettings(current.appearance, patch.appearance),
    shortcuts: mergeShortcutsSettings(current.shortcuts, patch.shortcuts)
  }
}

export function SettingsView(): ReactElement {
  const { t } = useTranslation('settings')
  const { t: tCommon } = useTranslation('common')
  const setRoute = useChatStore((s) => s.setRoute)
  const settingsSection = useChatStore((s) => s.settingsSection)
  const openSettings = useChatStore((s) => s.openSettings)
  const category: SettingsCategory = settingsSection
  const applyI18n = useChatStore((s) => s.applyI18nFromSettings)
  const reloadUiSettings = useChatStore((s) => s.reloadUiSettings)
  const probeRuntime = useChatStore((s) => s.probeRuntime)
  const usageRefreshKey = useChatStore((s) => s.usageRefreshKey)
  const composerModel = useChatStore((s) => s.composerModel)
  const composerModelMeta = useChatStore((s) => s.composerModelMeta)
  const [usageRange, setUsageRange] = useState<UsageRange>('30d')
  const persistentUsage = usePersistentUsage(usageRange, usageRefreshKey)
  const [form, setForm] = useState<AppSettingsV1 | null>(getSettingsSnapshot)
  const [settingsReady, setSettingsReady] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [workspacePickerError, setWorkspacePickerError] = useState<string | null>(null)
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle')
  const [saveError, setSaveError] = useState<string | null>(null)
  const [discardPrompt, setDiscardPrompt] = useState(false)
  const savingQueue = useRef<Promise<unknown>>(Promise.resolve())
  const leavingRef = useRef(false)
  const [petEnabled, setPetEnabled] = useState(() => readPetEnabled())
  const [petChatter, setPetChatter] = useState(() => readPetChatter())
  const [petAiLines, setPetAiLines] = useState(() => readPetAiLines())
  const [petSlug, setPetSlug] = useState(() => readPetSlug())
  const [popularPets, setPopularPets] = useState<PetPopularEntry[]>(() => [...BUNDLED_POPULAR_PETS])
  const [popularLoading, setPopularLoading] = useState(false)
  const petPopularRequested = useRef(false)
  const [logDirOpenError, setLogDirOpenError] = useState<string | null>(null)
  const [logDirPath, setLogDirPath] = useState('~/.deepseek/caches/logs')
  const [deepseekPaths, setDeepseekPaths] = useState({
    configPath: '~/.deepseek/config.toml',
    mcpPath: '~/.deepseek/mcp.json',
    hooksDir: '~/.deepseek/hooks',
    skillsDir: '~/.deepseek/skills'
  })
  const [hooksNotice, setHooksNotice] = useState<InlineNotice | null>(null)
  const initializedCategory = useRef(false)
  const saveTimer = useRef<number | null>(null)
  const statusTimer = useRef<number | null>(null)
  const draftVersion = useRef(0)
  const savedVersion = useRef(0)
  const formRef = useRef<AppSettingsV1 | null>(null)
  formRef.current = form
  const formTheme = form?.theme
  const formUiFontScale = form?.uiFontScale
  const formUiFontFamily = form?.uiFontFamily
  const formAppearance = form?.appearance
  const formShortcuts = form?.shortcuts
  const formWorkspaceRoot = form?.workspaceRoot
  const formPort = form?.deepseek.port

  useEffect(() => {
    return subscribePetPreferences(() => {
      setPetEnabled(readPetEnabled())
      setPetChatter(readPetChatter())
      setPetAiLines(readPetAiLines())
      setPetSlug(readPetSlug())
    })
  }, [])

  const loadPopularPets = useCallback(async (force = false): Promise<void> => {
    if (typeof window.dsGui?.fetchPopularPets !== 'function') return
    setPopularLoading(true)
    try {
      const result = await window.dsGui.fetchPopularPets(force)
      setPopularPets(result.pets)
    } finally {
      setPopularLoading(false)
    }
  }, [])

  useEffect(() => {
    if (category !== 'general' || petPopularRequested.current) return
    petPopularRequested.current = true
    void loadPopularPets()
  }, [category, loadPopularPets])

  const selectPetSlug = useCallback((pet: PetPickerItem): void => {
    setPetSlug(pet.slug)
    writePetSlug(pet.slug)
  }, [])

  const selectedPet = useMemo<PetPickerItem | null>(
    () => popularPets.find((pet) => pet.slug === petSlug) ?? null,
    [petSlug, popularPets]
  )

  useEffect(() => {
    let cancelled = false
    if (typeof window.dsGui === 'undefined') {
      setLoadError('PRELOAD_BRIDGE')
      return
    }
    void loadSettingsSnapshot()
      .then((s) => {
        if (!cancelled) { setForm(s); setSettingsReady(true) }
      })
      .catch((e: unknown) => {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : String(e))
      })
    if (typeof window.dsGui?.getDeepseekPaths === 'function') {
      void window.dsGui.getDeepseekPaths().then((paths) => {
        if (!cancelled) {
          setDeepseekPaths(paths)
        }
      })
    }
    if (typeof window.dsGui?.getLogPath === 'function') {
      void window.dsGui.getLogPath().then((path) => {
        if (!cancelled && path) setLogDirPath(path)
      })
    }
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!settingsReady || !formTheme || !formUiFontScale || !formUiFontFamily) return
    applyTheme(formTheme)
    applyUiFontScale(formUiFontScale)
    applyUiFontFamily(formUiFontFamily)
  }, [settingsReady, formTheme, formUiFontScale, formUiFontFamily])

  // Live preview: appearance edits repaint immediately while the debounced
  // save is still in flight (same pattern as theme/font scale above).
  useEffect(() => {
    if (!settingsReady || !formAppearance) return
    applyAppearance(formAppearance)
  }, [settingsReady, formAppearance])

  useEffect(() => {
    if (!settingsReady || !formShortcuts) return
    applyShortcutsSettings(formShortcuts)
  }, [settingsReady, formShortcuts])

  useEffect(() => {
    if (!settingsReady || !form || initializedCategory.current) return
    initializedCategory.current = true
    if (category === 'setup') return
    const hasBuiltinKey = Object.values(form.llmProviders ?? {}).some((entry) =>
      Boolean(entry?.apiKey?.trim())
    )
    const hasCustomKey = form.customEndpoints.some(
      (endpoint) => endpoint.enabled && endpoint.apiKey.trim()
    )
    if (!form.deepseek.apiKey?.trim() && !hasBuiltinKey && !hasCustomKey) {
      openSettings('models')
    }
  }, [settingsReady, form, openSettings, category])

  useEffect(() => {
    return () => {
      if (saveTimer.current) window.clearTimeout(saveTimer.current)
      if (statusTimer.current) window.clearTimeout(statusTimer.current)
    }
  }, [])

  const portError = useMemo(() => {
    if (typeof formPort !== 'number') return null
    if (!hasValidPort({ deepseek: { port: formPort } } as AppSettingsV1)) return t('portInvalid')
    return null
  }, [formPort, t])

  const openHooksConfigDir = async (): Promise<void> => {
    if (typeof window.dsGui?.openHooksDir !== 'function') return
    setHooksNotice(null)
    const result = await window.dsGui.openHooksDir()
    if (!result.ok) {
      setHooksNotice({ tone: 'error', message: result.message ?? t('applyFailed') })
    }
  }

  const persistSettings = async (snapshot: AppSettingsV1, version: number): Promise<boolean> => {
    if (!hasValidPort(snapshot)) {
      setSaveError(t('portInvalid'))
      setSaveStatus('error')
      return false
    }
    setSaveStatus('saving')
    setSaveError(null)

    try {
      const write = savingQueue.current.catch(() => undefined).then(() => window.dsGui.setSettings(snapshot))
      savingQueue.current = write
      const next = await write
      cacheSettingsSnapshot(next)
      savedVersion.current = version
      if (version !== draftVersion.current) return false

      formRef.current = next
      setForm(next)
      await applyI18n(next.locale)
      void reloadUiSettings()
      void probeRuntime('background')
      if (version !== draftVersion.current) return false

      setSaveStatus('saved')
      if (statusTimer.current) window.clearTimeout(statusTimer.current)
      statusTimer.current = window.setTimeout(() => {
        if (version === draftVersion.current) setSaveStatus('idle')
        statusTimer.current = null
      }, 1500)
      return true
    } catch (e) {
      if (version !== draftVersion.current) return false
      setSaveError(formatRuntimeError(e))
      setSaveStatus('error')
      return false
    }
  }

  const scheduleSave = (next: AppSettingsV1): void => {
    draftVersion.current += 1
    const version = draftVersion.current

    if (saveTimer.current) window.clearTimeout(saveTimer.current)
    if (statusTimer.current) window.clearTimeout(statusTimer.current)
    statusTimer.current = null
    setSaveError(null)

    if (!hasValidPort(next)) {
      setSaveStatus('idle')
      return
    }

    setSaveStatus('saving')
    saveTimer.current = window.setTimeout(() => {
      saveTimer.current = null
      void persistSettings(next, version)
    }, 450)
  }

  const flushPendingSave = async (): Promise<boolean> => {
    const snapshot = formRef.current
    if (!snapshot) return false
    if (savedVersion.current === draftVersion.current) return true
    draftVersion.current += 1
    const version = draftVersion.current

    if (saveTimer.current) {
      window.clearTimeout(saveTimer.current)
      saveTimer.current = null
    }
    if (statusTimer.current) {
      window.clearTimeout(statusTimer.current)
      statusTimer.current = null
    }

    return persistSettings(snapshot, version)
  }

  const goBack = (): void => {
    if (!formRef.current) { setRoute('chat'); return }
    if (leavingRef.current) return
    leavingRef.current = true
    void (async () => {
      try {
        if (!await flushPendingSave()) {
          setDiscardPrompt(true)
          return
        }
        await reloadUiSettings()
        setRoute('chat')
      } catch (error) {
        setSaveError(formatRuntimeError(error))
        setSaveStatus('error')
      } finally {
        leavingRef.current = false
      }
    })()
  }
  const goBackRef = useRef(goBack)
  goBackRef.current = goBack

  useEffect(() => {
    setSettingsLeaveHandler(() => {
      goBackRef.current()
    })
    return () => setSettingsLeaveHandler(null)
  }, [])

  if (category === 'setup') {
    return (
      <div className="ds-settings-page ds-page-scroll ds-no-drag flex h-full min-h-0 min-w-0 flex-1 items-center justify-center overflow-y-auto px-8 py-12 sm:px-10">
        <div className="w-full translate-y-4 sm:translate-y-6">
          <InitialSetupPanel />
        </div>
      </div>
    )
  }

  if (loadError) {
    const msg =
      loadError === 'PRELOAD_BRIDGE' ? t('preloadBridgeError') : t('loadFailed', { message: loadError })
    return (
      <div className="ds-settings-page flex h-full flex-col items-center justify-center gap-4 p-6 text-center">
        <p className="max-w-md text-sm text-red-700 dark:text-red-300">{msg}</p>
        <button
          type="button"
          className="inline-flex items-center justify-center rounded-xl bg-ds-userbubble px-4 py-2 text-center text-sm font-medium leading-none text-ds-userbubbleFg"
          onClick={goBack}
        >
          {t('back')}
        </button>
      </div>
    )
  }

  if (!form) {
    return (
      <div className="ds-settings-page flex h-full items-center justify-center text-ds-faint">
        {t('loading')}
      </div>
    )
  }

  const update = (partial: SettingsPatch): void => {
    const current = formRef.current
    if (!current || !settingsReady) return
    const next = mergeSettings(current, partial)
    formRef.current = next
    setForm(next)
    if (partial.locale) void applyI18n(partial.locale)
    scheduleSave(next)
  }

  const pickWorkspace = async (): Promise<void> => {
    try {
      setWorkspacePickerError(null)
      if (typeof window.dsGui?.pickWorkspaceDirectory !== 'function') {
        throw new Error('workspace:pick-directory unavailable')
      }
      const picked = await window.dsGui.pickWorkspaceDirectory(form.workspaceRoot || undefined)
      if (!picked.canceled && picked.path) {
        update({ workspaceRoot: picked.path })
      }
    } catch (e) {
      setWorkspacePickerError(formatWorkspacePickerError(e))
    }
  }

  const resetWorkspaceToDefault = (): void => {
    setWorkspacePickerError(null)
    update({ workspaceRoot: DEFAULT_WORKSPACE_ROOT })
  }

  return (
    <div inert={!settingsReady} aria-busy={!settingsReady} className="ds-settings-page ds-page-scroll ds-no-drag h-full min-h-0 min-w-0 flex-1 overflow-y-auto px-8 py-10 sm:px-10">
      <div className={`mx-auto ${category === 'archive' ? 'max-w-[880px]' : 'max-w-[836px]'}`}>
          {!Object.values(form.llmProviders ?? {}).some((entry) => entry?.apiKey?.trim()) &&
          !form.customEndpoints.some((endpoint) => endpoint.enabled && endpoint.apiKey.trim()) &&
          category === 'models' ? (
            <div className="mb-6 rounded-2xl border border-amber-300/80 bg-amber-50/95 px-5 py-4 text-amber-950 shadow-sm dark:border-amber-700/60 dark:bg-amber-950/35 dark:text-amber-100">
              <div className="text-[15px] font-semibold">{t('apiKeyRequiredTitle')}</div>
              <p className="mt-1 text-[13px] leading-6 text-amber-900/90 dark:text-amber-100/90">
                {t('apiKeyRequiredBody')}
              </p>
            </div>
          ) : null}

          <div className="mb-8 flex items-start justify-between gap-4">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-ds-ink">
                {category === 'browser' ? t('browserTitle') : category === 'computer-control' ? t('cuaTitle') : category === 'import' ? t('sessionImport.title') : category === 'models'
                  ? t('models')
                  : category === 'search'
                    ? t('search')
                    : category === 'shortcuts'
                      ? t('shortcuts')
                      : category === 'appearance'
                        ? t('appearance')
                        : category === 'data'
                          ? t('data')
                          : category === 'archive'
                            ? t('archive')
                            : t('title')}
              </h1>
              <p className="mt-1 text-[14px] text-ds-muted">
                {category === 'browser' ? t('browserDescription') : category === 'computer-control' ? t('cuaDescription') : category === 'import' ? t('sessionImport.subtitle') : category === 'data'
                  ? t('dataSubtitle')
                  : category === 'archive'
                    ? t('archiveSubtitle')
                    : category === 'search'
                      ? t('searchSubtitle')
                      : category === 'appearance'
                        ? t('appearanceSubtitle')
                        : t('subtitle')}
              </p>
            </div>
            {category !== 'data' && category !== 'archive' && category !== 'import' ? (
              <span
                title={saveStatus === 'error' && saveError ? saveError : undefined}
                className={`shrink-0 rounded-full px-3 py-1 text-[12px] font-medium ${
                  portError
                    ? 'bg-amber-500/15 text-amber-700 dark:text-amber-200'
                    : saveStatus === 'saved'
                      ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-200'
                      : saveStatus === 'error'
                        ? 'bg-red-500/15 text-red-700 dark:text-red-200'
                        : 'bg-ds-subtle text-ds-muted'
                }`}
              >
                {portError
                  ? t('autoApplyBlocked')
                  : saveStatus === 'saving'
                    ? t('applying')
                    : saveStatus === 'saved'
                      ? t('applied')
                      : saveStatus === 'error'
                        ? t('applyFailed')
                        : t('autoApplyHint')}
              </span>
            ) : null}
          </div>

          {saveStatus === 'error' && saveError ? (
            <GlobalErrorNotice title={t('settingsSaveFailedRetained')} message={saveError} actions={
              <button type="button" className="underline" onClick={() => void flushPendingSave()}>{t('settingsRetrySave')}</button>
            } />
          ) : null}
          {discardPrompt ? (
            <ConfirmDialog
              title={t('settingsUnsavedTitle')}
              body={t('settingsUnsavedBody')}
              destructive
              confirmLabel={t('settingsDiscardAndLeave')}
              cancelLabel={t('settingsKeepEditing')}
              onCancel={() => setDiscardPrompt(false)}
              onConfirm={() => {
                if (saveTimer.current) window.clearTimeout(saveTimer.current)
                draftVersion.current += 1
                void savingQueue.current.catch(() => undefined).then(async () => {
                  await reloadUiSettings()
                  setRoute('chat')
                }).catch((error) => {
                  setDiscardPrompt(false)
                  setSaveError(formatRuntimeError(error))
                  setSaveStatus('error')
                })
              }}
            />
          ) : null}

          {category === 'general' && (
            <>
              <SettingsCard title={t('sectionGeneral')}>
                <SettingRow
                  title={t('language')}
                  description={t('languageDesc')}
                  control={
                    <SettingsSelect
                      value={form.locale}
                      onChange={(e) => update({ locale: e.target.value as 'en' | 'zh' })}
                    >
                      <option value="en">English</option>
                      <option value="zh">简体中文</option>
                    </SettingsSelect>
                  }
                />
                <SettingRow
                  title={t('externalApp')}
                  description={t('externalAppDesc')}
                  control={<DefaultEditorPicker />}
                />
                <SettingRow
                  title={t('autoStart')}
                  description={t('autoStartDesc')}
                  control={
                    <Toggle
                      checked={form.deepseek.autoStart}
                      onChange={(v) => update({ deepseek: { autoStart: v } })}
                    />
                  }
                />
                <SettingRow
                  title={t('port')}
                  description={t('portDesc')}
                  control={
                    <div>
                      <input
                        type="number"
                        min={1}
                        max={65535}
                        className={`w-28 rounded-xl border bg-ds-card px-3 py-2 text-[14px] text-ds-ink shadow-sm focus:outline-none focus:ring-1 ${
                          portError
                            ? 'border-red-400 focus:ring-red-300'
                            : 'border-ds-border focus:border-accent/40 focus:ring-accent/30'
                        }`}
                        value={form.deepseek.port}
                        onChange={(e) => update({ deepseek: { port: Number(e.target.value) } })}
                      />
                      {portError ? (
                        <p className="mt-1 text-[12px] text-red-700 dark:text-red-300">{portError}</p>
                      ) : null}
                    </div>
                  }
                />
                <SettingRow
                  title={t('turnCompleteNotification')}
                  description={t('turnCompleteNotificationDesc')}
                  control={
                    <Toggle
                      checked={form.notifications.turnComplete}
                      onChange={(v) => update({ notifications: { turnComplete: v } })}
                    />
                  }
                />
                <SettingRow
                  title={t('iconAnimation')}
                  description={t('iconAnimationDesc')}
                  control={
                    <Toggle
                      checked={form.iconAnimation}
                      onChange={(v) => update({ iconAnimation: v })}
                    />
                  }
                />
                <div className="ds-density-row flex flex-col gap-4 px-4 py-5">
                  {/* Title line + 还原默认 aligned to the title. */}
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="flex items-center gap-1 text-[14px] font-semibold text-ds-ink">
                        <span>{t('workspaceRoot')}</span>
                      </div>
                      <p className="mt-1 max-w-2xl text-[13px] leading-6 text-ds-muted">
                        {t('workspaceRootDesc')}
                      </p>
                    </div>
                    <div className="w-[8.5rem] shrink-0">
                      <button
                        type="button"
                        onClick={resetWorkspaceToDefault}
                        className={settingsBlockButtonClass()}
                      >
                        {t('restoreWorkspaceDefault')}
                      </button>
                    </div>
                  </div>
                  {/* Address input + 选择目录 aligned to the input. */}
                  <div className="flex w-full min-w-0 flex-col gap-2">
                    <div className="flex w-full items-center gap-4">
                      <input
                        className="w-full min-w-0 flex-1 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[14px] text-ds-ink shadow-sm focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30"
                        value={form.workspaceRoot}
                        onChange={(e) => update({ workspaceRoot: e.target.value })}
                        placeholder={t('workspaceRootPlaceholder')}
                        title={form.workspaceRoot}
                      />
                      <div className="w-[8.5rem] shrink-0">
                        <button
                          type="button"
                          onClick={() => void pickWorkspace()}
                          className={settingsBlockButtonClass()}
                        >
                          {t('browse')}
                        </button>
                      </div>
                    </div>
                    {workspacePickerError ? (
                      <p className="text-[13px] leading-5 text-amber-700 dark:text-amber-300">
                        {workspacePickerError}
                      </p>
                    ) : null}
                  </div>
                </div>
                <SettingRow
                  relaxed
                  title={t('logDir')}
                  description={
                    <span className="flex flex-col gap-1">
                      <span>{t('logDirDesc')}</span>
                      <span className="break-all font-mono text-[12px] text-ds-muted" title={logDirPath}>
                        {logDirPath}
                      </span>
                    </span>
                  }
                  controlWidth="medium"
                  control={
                    <div className="flex w-full flex-col items-end gap-1.5">
                      <button
                        type="button"
                        className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-xl border border-ds-border bg-ds-card px-3 py-1.5 text-center text-[13px] font-medium leading-none text-ds-ink shadow-sm transition hover:bg-ds-hover disabled:opacity-50"
                        disabled={typeof window.dsGui?.openLogDir !== 'function'}
                        onClick={async () => {
                          if (typeof window.dsGui?.openLogDir !== 'function') return
                          setLogDirOpenError(null)
                          try {
                            const result = await window.dsGui.openLogDir()
                            if (!result.ok) setLogDirOpenError(result.message ?? 'Unknown error')
                          } catch (e) {
                            setLogDirOpenError(e instanceof Error ? e.message : String(e))
                          }
                        }}
                      >
                        <FolderOpen className="h-4 w-4" />
                        {t('logDirOpen')}
                      </button>
                      {logDirOpenError ? (
                        <p className="max-w-[280px] text-right text-[12px] text-red-700 dark:text-red-300">
                          {logDirOpenError}
                        </p>
                      ) : null}
                    </div>
                  }
                />
              </SettingsCard>

              <SettingsCard title={t('sectionPet')} className="mt-6">
                <SettingRow
                  title={t('petMascotEnabled')}
                  description={t('petMascotEnabledDesc')}
                  control={
                    <Toggle
                      checked={petEnabled}
                      onChange={(value) => {
                        setPetEnabled(value)
                        writePetEnabled(value)
                      }}
                    />
                  }
                />
                <div className="px-3 py-4">
                  <PetPicker
                    enabled={petEnabled}
                    selectedSlug={petSlug}
                    selectedPet={selectedPet}
                    popular={popularPets}
                    popularLoading={popularLoading}
                    onRefreshPopular={() => void loadPopularPets(true)}
                    onSelect={selectPetSlug}
                  />
                </div>
                <SettingRow
                  title={t('petChatterTitle')}
                  description={t('petChatterDesc')}
                  control={
                    <Toggle
                      checked={petChatter}
                      disabled={!petEnabled}
                      onChange={(value) => {
                        setPetChatter(value)
                        writePetChatter(value)
                      }}
                    />
                  }
                />
                <SettingRow
                  title={t('petAiLinesTitle')}
                  description={t('petAiLinesDesc')}
                  control={
                    <Toggle
                      checked={petAiLines}
                      disabled={!petEnabled || !petChatter}
                      onChange={(value) => {
                        setPetAiLines(value)
                        writePetAiLines(value)
                      }}
                    />
                  }
                />
              </SettingsCard>
            </>
          )}

          {category === 'browser' && <BrowserSettingsPanel form={form} onUpdate={update} />}
          {category === 'computer-control' && (
            <CuaSettingsPanel form={form} onUpdate={(patch) => update(patch)} />
          )}

          {category === 'search' && (
            <WebSearchSettingsPanel form={form} onUpdate={(patch) => update(patch)} />
          )}

          {category === 'appearance' && (
            <AppearanceSettingsPanel form={form} onPatch={(patch) => update(patch)} />
          )}

          {category === 'shortcuts' && (
            <SettingsCard title={t('shortcutsSection')}>
              {SHORTCUT_CATALOG.map((item) => {
                const enabled = form.shortcuts[item.id]?.enabled !== false
                const label = formatShortcutLabel(item.chord)
                return (
                  <div
                    key={item.id}
                    className={`transition-opacity duration-150 ${enabled ? '' : 'opacity-45'}`}
                  >
                    <SettingRow
                      alignControl="center"
                      controlWidth="medium"
                      title={t(`shortcut_${item.id}_title`)}
                      description={t(`shortcut_${item.id}_desc`)}
                      control={
                        <div className="flex items-center justify-end gap-3">
                          <ShortcutKeycaps chord={item.chord} label={label} />
                          <Toggle
                            checked={enabled}
                            onChange={(next) =>
                              update({
                                shortcuts: { [item.id]: { enabled: next } } as ShortcutsPatchV1
                              })
                            }
                          />
                        </div>
                      }
                    />
                  </div>
                )
              })}
            </SettingsCard>
          )}

          {category === 'models' && (
            <>
              <SettingsCard title={t('llmProvidersTitle')}>
                <LlmProvidersPanel form={form} onUpdate={(patch) => update(patch)} />
              </SettingsCard>

              <SettingsCard title={t('modelUsageSection')} className="mt-6">
                <ModelUsagePanel
                  usage={persistentUsage.data?.summary ?? null}
                  daily={persistentUsage.data?.daily ?? []}
                  loading={persistentUsage.loading}
                  loaded={persistentUsage.loaded}
                  error={persistentUsage.error}
                  activeModelId={composerModel}
                  composerModelMeta={composerModelMeta}
                  range={usageRange}
                  onRangeChange={setUsageRange}
                />
              </SettingsCard>
            </>
          )}

          {category === 'permissions' && (
            <>
              <SettingsCard title={t('permissions')}>
                <SettingRow
                  title={t('approvalPolicy')}
                  help={
                    <FieldHelpPopover title={t('approvalPolicy')} intro={t('approvalPolicyHelp')} />
                  }
                  description={t('approvalPolicyDesc')}
                  control={
                    <SettingsSelect
                      value={
                        form.deepseek.approvalPolicy === 'suggest'
                          ? 'on-request'
                          : form.deepseek.approvalPolicy
                      }
                      onChange={(e) => {
                        const approvalPolicy = e.target.value as ApprovalPolicy
                        update({
                          deepseek: {
                            approvalPolicy,
                            sandboxMode: sandboxModeForApprovalPolicy(approvalPolicy)
                          }
                        })
                      }}
                    >
                      <option value="on-request">{t('approvalOnRequest')}</option>
                      <option value="untrusted">{t('approvalUntrusted')}</option>
                      <option value="auto">{t('approvalAuto')}</option>
                      <option value="never">{t('approvalNever')}</option>
                    </SettingsSelect>
                  }
                />
                <SettingRow
                  title={t('sandboxMode')}
                  help={
                    <FieldHelpPopover title={t('sandboxMode')} intro={t('sandboxModeDerivedHelp')} />
                  }
                  description={t('sandboxModeDerivedDesc')}
                  control={
                    <div className="flex h-10 w-full min-w-0 items-center justify-center rounded-xl border border-ds-border bg-ds-card/70 px-3 text-center text-[14px] font-medium leading-none text-ds-muted shadow-sm">
                      {form.deepseek.approvalPolicy === 'auto'
                        ? t('sandboxFullAccess')
                        : t('sandboxWorkspaceWrite')}
                    </div>
                  }
                />
              </SettingsCard>
              <NetworkSettingsPanel form={form} onUpdate={update} />
            </>
          )}

          {category === 'hooks' && (
            <SettingsCard title={t('hooks')}>
              <SettingRow
                relaxed
                alignControl="center"
                title={t('hooksConfigPath')}
                help={
                  <FieldHelpPopover
                    title={t('hooksConfigPath')}
                    intro={t('hooksConfigPathDesc')}
                  />
                }
                description={
                  <p className="text-[13px] leading-6 text-ds-muted">{t('hooksDesc')}</p>
                }
                controlWidth="medium"
                control={
                  <div
                    className="w-full max-w-[280px] rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[13px] text-ds-muted shadow-sm"
                    title={`${deepseekPaths.configPath} · [hooks]`}
                  >
                    <code className="block truncate rounded-lg bg-ds-main/70 px-2 py-1 font-mono text-[12px] text-ds-ink">
                      {deepseekPaths.configPath} · [hooks]
                    </code>
                  </div>
                }
              />
              <SettingRow
                relaxed
                alignControl="center"
                title={t('hooksActions')}
                help={
                  <FieldHelpPopover
                    title={t('hooksActions')}
                    intro={t('hooksOpenConfigHint')}
                  />
                }
                description={
                  <p className="text-[13px] leading-6 text-ds-muted">{t('hooksActionsDesc')}</p>
                }
                control={
                  <div className="flex flex-col items-end gap-2">
                    <button
                      type="button"
                      onClick={() => void openHooksConfigDir()}
                      className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-center text-[13px] font-medium leading-none text-ds-ink shadow-sm transition hover:bg-ds-hover"
                    >
                      <FolderOpen className="h-4 w-4" />
                      {t('hooksOpenConfigDir')}
                    </button>
                    {hooksNotice ? (
                      <div className="w-full max-w-[280px]">
                        <InlineNoticeView notice={hooksNotice} />
                      </div>
                    ) : null}
                  </div>
                }
              />
            </SettingsCard>
          )}

          {category === 'data' && <><DataSettingsPanel /><SharingSettingsPanel /></>}
          {category === 'archive' && <ArchiveSettingsPanel />}
          {category === 'import' && <SessionImportPanel />}

      </div>
    </div>
  )
}

function SecretInput({
  value,
  onChange,
  visible,
  onToggleVisibility,
  placeholder,
  autoComplete,
  invalid = false,
  showLabel,
  hideLabel,
  className = ''
}: {
  value: string
  onChange: (value: string) => void
  visible: boolean
  onToggleVisibility: () => void
  placeholder?: string
  autoComplete?: string
  invalid?: boolean
  showLabel: string
  hideLabel: string
  className?: string
}): ReactElement {
  return (
    <div
      className={`flex w-full min-w-0 items-stretch overflow-hidden rounded-xl bg-ds-card shadow-sm ${className} ${
        invalid
          ? 'border border-amber-300 focus-within:border-amber-400 focus-within:ring-1 focus-within:ring-amber-200'
          : 'border border-ds-border focus-within:border-accent/40 focus-within:ring-1 focus-within:ring-accent/30'
      }`}
    >
      <input
        type={visible ? 'text' : 'password'}
        autoComplete={autoComplete}
        placeholder={placeholder}
        className="min-w-0 flex-1 bg-transparent px-3 py-2 text-[14px] text-ds-ink focus:outline-none"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <button
        type="button"
        aria-label={visible ? hideLabel : showLabel}
        title={visible ? hideLabel : showLabel}
        onClick={onToggleVisibility}
        className="inline-flex shrink-0 items-center justify-center self-stretch border-l border-ds-border-muted px-3 text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
      >
        {visible ? <EyeOff className="h-4 w-4" strokeWidth={1.75} /> : <Eye className="h-4 w-4" strokeWidth={1.75} />}
      </button>
    </div>
  )
}

function InlineNoticeView({
  notice
}: {
  notice: InlineNotice
}): ReactElement {
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
    <section
      className={`ds-content-card rounded-2xl ${className}`}
    >
      <div className="border-b border-ds-border-muted px-5 py-3">
        <h2 className="text-[16px] font-semibold text-ds-ink">{title}</h2>
      </div>
      <div className="divide-y divide-ds-border-muted px-2 py-1">{children}</div>
    </section>
  )
}

const settingControlWidthClass = {
  compact: 'sm:max-w-[210px]',
  medium: 'sm:max-w-[280px]',
  wide: 'sm:max-w-xl',
  full: 'sm:max-w-[420px]'
} as const

function SettingRow({
  title,
  description,
  help,
  control,
  wideControl = false,
  relaxed = false,
  layout = 'default',
  alignControl = 'start',
  controlWidth = 'compact'
}: {
  title: string
  description?: ReactNode
  help?: ReactNode
  control: ReactNode
  wideControl?: boolean
  relaxed?: boolean
  layout?: 'default' | 'stacked'
  alignControl?: 'start' | 'center'
  controlWidth?: keyof typeof settingControlWidthClass
}): ReactElement {
  const descriptionNode =
    typeof description === 'string' ? (
      <p
        className={
          layout === 'stacked' || relaxed
            ? 'mt-1 max-w-2xl text-[13px] leading-6 text-ds-muted'
            : 'mt-0.5 max-w-md text-pretty text-[13px] leading-relaxed text-ds-muted break-keep'
        }
      >
        {description}
      </p>
    ) : description ? (
      <div
        className={
          layout === 'stacked' || relaxed ? 'mt-1 max-w-2xl space-y-2' : 'mt-0.5 max-w-md'
        }
      >
        {description}
      </div>
    ) : null

  const titleNode = (
    <div className="flex items-center gap-1 text-[14px] font-semibold text-ds-ink">
      <span>{title}</span>
      {help}
    </div>
  )

  if (layout === 'stacked') {
    return (
      <div className="ds-density-row flex flex-col gap-4 px-4 py-5">
        <div className="min-w-0">
          {titleNode}
          {descriptionNode}
        </div>
        <div className="w-full min-w-0">{control}</div>
      </div>
    )
  }

  const rowAlignClass =
    alignControl === 'center' ? 'sm:items-center' : 'sm:items-start'

  return (
    <div
      className={`ds-setting-row ds-density-row flex ${
        wideControl
          ? 'flex-col gap-3.5 px-3 py-4 sm:px-4'
          : relaxed
            ? `flex-col gap-4 px-4 py-5 sm:flex-row ${rowAlignClass} sm:justify-between sm:gap-10`
            : `flex-col gap-3 px-3 py-4 sm:flex-row ${rowAlignClass} sm:justify-between sm:gap-8`
      }`}
    >
      <div
        className={`min-w-0 ${
          wideControl
            ? 'w-full max-w-none shrink-0'
            : relaxed
              ? 'flex-1 sm:min-w-[220px] sm:max-w-[52%] sm:pr-6'
              : 'flex-1'
        }`}
      >
        {titleNode}
        {descriptionNode}
      </div>
      <div
        className={`w-full min-w-0 sm:ml-auto sm:shrink-0 ${
          wideControl ? '' : settingControlWidthClass[controlWidth]
        }`}
      >
        {wideControl || controlWidth === 'full' ? (
          control
        ) : (
          <div
            className={`flex w-full ${
              alignControl === 'center' ? 'justify-center sm:justify-end' : 'justify-end'
            }`}
          >
            {control}
          </div>
        )}
      </div>
    </div>
  )
}

function GroupedField({
  title,
  help,
  control
}: {
  title: string
  help?: ReactNode
  control: ReactNode
}): ReactElement {
  return (
    <div className="ds-density-row flex flex-col gap-2 px-5 py-3 sm:flex-row sm:items-center sm:gap-5">
      <div className="flex min-w-0 items-center gap-1.5 sm:w-[180px] sm:shrink-0">
        <span className="text-[13px] font-medium text-ds-ink">{title}</span>
        {help}
      </div>
      <div className="min-w-0 flex-1 sm:ml-auto sm:max-w-[360px]">{control}</div>
    </div>
  )
}

function ShortcutKeycaps({
  chord,
  label
}: {
  chord: ShortcutChord
  label: string
}): ReactElement {
  const tokens = shortcutChordTokens(chord)
  return (
    <div className="ds-shortcut-keys shrink-0" aria-label={label}>
      {tokens.map((token, index) => (
        <kbd
          key={`${token}-${index}`}
          className={`ds-keycap${token.length > 1 ? ' ds-keycap--wide' : ''}`}
        >
          {token}
        </kbd>
      ))}
    </div>
  )
}

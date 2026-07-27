import type { ReactElement, ReactNode } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  mergeAppearanceSettings,
  mergeClawSettings,
  mergeLlmProviders,
  mergeShortcutsSettings,
  sandboxModeForApprovalPolicy,
  type AppearancePatchV1,
  type ApprovalPolicy,
  type AppSettingsV1,
  type BuiltinLlmProviderId,
  type ClawSettingsPatchV1,
  type LlmProviderConfigV1,
  type ShortcutsPatchV1
} from '@shared/app-settings'
import {
  SHORTCUT_CATALOG,
  formatShortcutLabel,
  shortcutChordTokens,
  type ShortcutChord
} from '@shared/shortcuts'
import {
  Anchor,
  Box,
  ChevronDown,
  ChevronLeft,
  Eye,
  EyeOff,
  FolderOpen,
  Globe,
  Keyboard,
  Loader2,
  Palette,
  RefreshCw,
  Settings,
  Shield,
  Archive,
  HardDrive,
  PawPrint,
  X
} from 'lucide-react'
import type { PetManifestEntry } from '@shared/pet-manifest'
import { applyTheme, applyUiFontScale, applyUiFontFamily } from '../lib/apply-theme'
import { applyAppearance } from '../lib/apply-appearance'
import { applyShortcutsSettings } from '../lib/shortcuts-runtime'
import { formatWorkspacePickerError } from '../lib/format-workspace-picker-error'
import {
  readPetEnabled,
  readPetFavoriteSlugs,
  readPetSlug,
  subscribePetPreferences,
  writePetEnabled,
  writePetFavoriteSlugs,
  writePetSlug
} from '../lib/pet/pet-preferences'
import { resolvePetSpritesheetSrc } from '../lib/pet/pet-catalog'
import { filterManifestPets } from '@shared/pet-catalog-utils'
import { DEFAULT_WORKSPACE_ROOT } from '@shared/workspace-defaults'
import { normalizeWorkspaceRoot } from '../lib/workspace-path'
import { useChatStore, type SettingsRouteSection } from '../store/chat-store'
import { AppearanceSettingsPanel } from './settings/AppearanceSettingsPanel'
import { ArchiveSettingsPanel } from './settings/ArchiveSettingsPanel'
import { DataSettingsPanel } from './settings/DataSettingsPanel'
import { LlmProvidersPanel } from './settings/LlmProvidersPanel'
import { ModelUsagePanel } from './settings/ModelUsagePanel'
import { settingsBlockButtonClass } from './settings/SettingsActionToolbar'
import { SettingsSelect } from './settings/SettingsSelect'
import { PetSprite } from './pet/PetSprite'
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
  const [form, setForm] = useState<AppSettingsV1 | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [workspacePickerError, setWorkspacePickerError] = useState<string | null>(null)
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle')
  const [saveError, setSaveError] = useState<string | null>(null)
  const [petEnabled, setPetEnabled] = useState(() => readPetEnabled())
  const [petSlug, setPetSlug] = useState(() => readPetSlug())
  const [petFavoriteSlugs, setPetFavoriteSlugs] = useState(() => readPetFavoriteSlugs())
  const [favoritePets, setFavoritePets] = useState<PetManifestEntry[]>([])
  const [petCatalogPets, setPetCatalogPets] = useState<PetManifestEntry[]>([])
  const [petCatalogQuery, setPetCatalogQuery] = useState('')
  const [petCachedSlugs, setPetCachedSlugs] = useState<Set<string>>(() => new Set())
  const [petCatalogLoading, setPetCatalogLoading] = useState(false)
  const [petCatalogError, setPetCatalogError] = useState<string | null>(null)
  const [logDirOpenError, setLogDirOpenError] = useState<string | null>(null)
  const [deepseekPaths, setDeepseekPaths] = useState({
    configPath: '~/.deepseek/config.toml',
    mcpPath: '~/.deepseek/mcp.json',
    hooksDir: '~/.deepseek/hooks',
    skillsDir: '~/.deepseek/skills'
  })
  const [hooksNotice, setHooksNotice] = useState<InlineNotice | null>(null)
  const initializedCategory = useRef(false)
  const saveTimer = useRef<ReturnType<typeof window.setTimeout> | null>(null)
  const statusTimer = useRef<ReturnType<typeof window.setTimeout> | null>(null)
  const draftVersion = useRef(0)
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
      setPetSlug(readPetSlug())
      setPetFavoriteSlugs(readPetFavoriteSlugs())
    })
  }, [])

  const cachePetSlugs = useCallback((slugs: string[]): void => {
    if (typeof window.dsGui?.resolvePetSpritesheet !== 'function') return
    void Promise.allSettled(slugs.map((slug) => window.dsGui.resolvePetSpritesheet(slug))).then(
      (results) => {
        setPetCachedSlugs((current) => {
          const next = new Set(current)
          for (const result of results) {
            if (result.status === 'fulfilled' && result.value.ok) {
              next.add(result.value.slug)
            }
          }
          return next
        })
      }
    )
  }, [])

  const applyFavoriteSlugs = useCallback((slugs: string[], catalog: PetManifestEntry[]): void => {
    const bySlug = new Map(catalog.map((pet) => [pet.slug, pet]))
    const normalized = slugs.slice(0, 15)
    setPetFavoriteSlugs(normalized)
    setFavoritePets(
      normalized.map(
        (slug) =>
          bySlug.get(slug) ?? {
            slug,
            displayName: slug,
            kind: 'creature',
            submittedBy: null,
            spritesheetUrl: '',
            petJsonUrl: '',
            zipUrl: null
          }
      )
    )
  }, [])

  const loadPetCatalog = useCallback(async (force = false): Promise<void> => {
    if (typeof window.dsGui?.fetchPetManifest !== 'function') return
    setPetCatalogLoading(true)
    setPetCatalogError(null)
    try {
      const result = await window.dsGui.fetchPetManifest(force)
      if (!result.ok) {
        setPetCatalogError(result.message)
        return
      }
      const catalog = result.manifest.pets
      setPetCatalogPets(catalog)
      let favoriteSlugs = readPetFavoriteSlugs()
      if (favoriteSlugs.length === 0) {
        favoriteSlugs = catalog.slice(0, 15).map((pet) => pet.slug)
        writePetFavoriteSlugs(favoriteSlugs)
      }
      applyFavoriteSlugs(favoriteSlugs, catalog)
      cachePetSlugs(favoriteSlugs)
    } catch (error) {
      applyFavoriteSlugs(readPetFavoriteSlugs(), petCatalogPets)
      setPetCatalogError(error instanceof Error ? error.message : String(error))
    } finally {
      setPetCatalogLoading(false)
    }
  }, [applyFavoriteSlugs, cachePetSlugs, petCatalogPets])

  useEffect(() => {
    if (category !== 'general') return
    if (favoritePets.length > 0 || petCatalogLoading) return
    void loadPetCatalog()
  }, [category, favoritePets.length, loadPetCatalog, petCatalogLoading])

  const selectPetSlug = useCallback(async (pet: PetManifestEntry): Promise<void> => {
    setPetSlug(pet.slug)
    writePetSlug(pet.slug)
    if (!petCachedSlugs.has(pet.slug) && typeof window.dsGui?.resolvePetSpritesheet === 'function') {
      const result = await window.dsGui.resolvePetSpritesheet(pet.slug)
      if (result.ok) {
        setPetCachedSlugs((current) => new Set(current).add(result.slug))
      }
    }
  }, [petCachedSlugs])

  const addFavoritePet = useCallback(
    (pet: PetManifestEntry): void => {
      const next = [pet.slug, ...petFavoriteSlugs.filter((slug) => slug !== pet.slug)].slice(0, 15)
      writePetFavoriteSlugs(next)
      applyFavoriteSlugs(next, petCatalogPets)
      cachePetSlugs([pet.slug])
    },
    [applyFavoriteSlugs, cachePetSlugs, petCatalogPets, petFavoriteSlugs]
  )

  const removeFavoritePet = useCallback(
    (slug: string): void => {
      const next = petFavoriteSlugs.filter((item) => item !== slug)
      writePetFavoriteSlugs(next)
      applyFavoriteSlugs(next, petCatalogPets)
    },
    [applyFavoriteSlugs, petCatalogPets, petFavoriteSlugs]
  )

  const petSearchResults = useMemo(() => {
    if (petCatalogPets.length === 0) return []
    const favoriteSet = new Set(petFavoriteSlugs)
    return filterManifestPets(petCatalogPets.length ? {
      generatedAt: '',
      total: petCatalogPets.length,
      pets: petCatalogPets
    } : { generatedAt: '', total: 0, pets: [] }, petCatalogQuery, 10).filter(
      (pet) => !favoriteSet.has(pet.slug)
    )
  }, [petCatalogPets, petCatalogQuery, petFavoriteSlugs])

  useEffect(() => {
    let cancelled = false
    if (typeof window.dsGui === 'undefined') {
      setLoadError('PRELOAD_BRIDGE')
      return
    }
    void window.dsGui
      .getSettings()
      .then((s) => {
        if (!cancelled) setForm(s)
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
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!formTheme || !formUiFontScale || !formUiFontFamily) return
    applyTheme(formTheme)
    applyUiFontScale(formUiFontScale)
    applyUiFontFamily(formUiFontFamily)
  }, [formTheme, formUiFontScale, formUiFontFamily])

  // Live preview: appearance edits repaint immediately while the debounced
  // save is still in flight (same pattern as theme/font scale above).
  useEffect(() => {
    if (!formAppearance) return
    applyAppearance(formAppearance)
  }, [formAppearance])

  useEffect(() => {
    if (!formShortcuts) return
    applyShortcutsSettings(formShortcuts)
  }, [formShortcuts])

  useEffect(() => {
    if (!form || initializedCategory.current) return
    initializedCategory.current = true
    const hasBuiltinKey = Object.values(form.llmProviders ?? {}).some((entry) =>
      Boolean(entry?.apiKey?.trim())
    )
    const hasCustomKey = form.customEndpoints.some(
      (endpoint) => endpoint.enabled && endpoint.apiKey.trim()
    )
    if (!form.deepseek.apiKey?.trim() && !hasBuiltinKey && !hasCustomKey) {
      openSettings('models')
    }
  }, [form, openSettings])

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

  const persistSettings = async (snapshot: AppSettingsV1, version: number): Promise<void> => {
    if (!hasValidPort(snapshot)) return
    setSaveStatus('saving')
    setSaveError(null)

    try {
      const next = await window.dsGui.setSettings(snapshot)
      if (version !== draftVersion.current) return

      setForm(next)
      await applyI18n(next.locale)
      void reloadUiSettings()
      void probeRuntime('background')
      if (version !== draftVersion.current) return

      setSaveStatus('saved')
      if (statusTimer.current) window.clearTimeout(statusTimer.current)
      statusTimer.current = window.setTimeout(() => {
        if (version === draftVersion.current) setSaveStatus('idle')
        statusTimer.current = null
      }, 1500)
    } catch (e) {
      if (version !== draftVersion.current) return
      setSaveError(e instanceof Error ? e.message : String(e))
      setSaveStatus('error')
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

  const flushPendingSave = async (): Promise<void> => {
    if (!form || !hasValidPort(form)) return
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

    await persistSettings(form, version)
  }

  const goBack = (): void => {
    void (async () => {
      await flushPendingSave()
      await reloadUiSettings()
      setRoute('chat')
    })()
  }

  if (loadError) {
    const msg =
      loadError === 'PRELOAD_BRIDGE' ? t('preloadBridgeError') : t('loadFailed', { message: loadError })
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-6 text-center">
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
      <div className="flex h-full items-center justify-center text-ds-faint">
        {t('loading')}
      </div>
    )
  }

  const update = (partial: SettingsPatch): void => {
    const next = mergeSettings(form, partial)
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

  const catCls = (c: SettingsCategory): string =>
    `flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-[13.5px] font-medium transition ${
      category === c
        ? 'bg-ds-hover text-ds-ink'
        : 'text-ds-muted hover:bg-ds-hover/60 hover:text-ds-ink'
    }`
  return (
    <div className="ds-settings-page ds-drag flex h-full min-h-0 w-full min-w-0">
      <aside className="ds-sidebar-shell ds-settings-sidebar ds-drag flex w-[260px] shrink-0 flex-col">
        <div className="px-3 pb-3 pt-3">
          <div aria-hidden className="ds-titlebar-safe-block" />
          <button
            type="button"
            onClick={goBack}
            className="ds-no-drag flex items-center gap-2 rounded-xl px-2 py-2 text-[14px] text-ds-muted hover:bg-ds-hover hover:text-ds-ink"
          >
            <ChevronLeft className="h-4 w-4" strokeWidth={1.75} />
            {t('back')}
          </button>
        </div>
        <nav className="ds-no-drag flex flex-col gap-0.5 px-2">
          <button type="button" className={catCls('general')} onClick={() => openSettings('general')}>
            <Globe className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
            {t('general')}
          </button>
          <button
            type="button"
            className={catCls('appearance')}
            onClick={() => openSettings('appearance')}
          >
            <Palette className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
            {t('appearance')}
          </button>
          <button
            type="button"
            className={catCls('shortcuts')}
            onClick={() => openSettings('shortcuts')}
          >
            <Keyboard className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
            {t('shortcuts')}
          </button>
          <button type="button" className={catCls('models')} onClick={() => openSettings('models')}>
            <Box className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
            {t('models')}
          </button>
          <button type="button" className={catCls('hooks')} onClick={() => openSettings('hooks')}>
            <Anchor className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
            {t('hooks')}
          </button>
          <button type="button" className={catCls('permissions')} onClick={() => openSettings('permissions')}>
            <Shield className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
            {t('permissions')}
          </button>
          <button type="button" className={catCls('data')} onClick={() => openSettings('data')}>
            <HardDrive className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
            {t('data')}
          </button>
          <button type="button" className={catCls('archive')} onClick={() => openSettings('archive')}>
            <Archive className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
            {t('archive')}
          </button>
        </nav>
        <div className="ds-no-drag mt-auto border-t border-ds-border p-3">
          <div className="flex items-center gap-2 rounded-xl px-2 py-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-ds-subtle text-ds-muted">
              <Settings className="h-4 w-4" strokeWidth={1.75} />
            </div>
            <div className="min-w-0 truncate text-[13px] font-medium text-ds-ink">
              {t('settingsFooter')}
            </div>
          </div>
        </div>
      </aside>

      <div className="ds-page-scroll ds-no-drag min-h-0 min-w-0 flex-1 overflow-y-auto px-8 py-10 sm:px-10">
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
                {category === 'models'
                  ? t('models')
                  : category === 'shortcuts'
                    ? t('shortcuts')
                    : category === 'data'
                      ? t('data')
                      : category === 'archive'
                        ? t('archive')
                        : t('title')}
              </h1>
              <p className="mt-1 text-[14px] text-ds-muted">
                {category === 'data'
                  ? t('dataSubtitle')
                  : category === 'archive'
                    ? t('archiveSubtitle')
                    : t('subtitle')}
              </p>
            </div>
            {category !== 'data' && category !== 'archive' ? (
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
                  description={t('logDirDesc')}
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
                  controlWidth="full"
                  title={t('petMascotEnabled')}
                  description={
                    <PetMascotSettingPreview
                      enabled={petEnabled}
                      selectedSlug={petSlug}
                      selectedName={
                        favoritePets.find((pet) => pet.slug === petSlug)?.displayName ?? petSlug
                      }
                      description={t('petMascotEnabledDesc')}
                    />
                  }
                  control={
                    <PetMascotSettingsControl
                      enabled={petEnabled}
                      selectedSlug={petSlug}
                      favoritePets={favoritePets}
                      favoriteCount={petFavoriteSlugs.length}
                      searchQuery={petCatalogQuery}
                      searchResults={petSearchResults}
                      loading={petCatalogLoading}
                      error={petCatalogError}
                      onEnabledChange={(value) => {
                        setPetEnabled(value)
                        writePetEnabled(value)
                      }}
                      onRefresh={() => void loadPetCatalog(true)}
                      onSearchQueryChange={setPetCatalogQuery}
                      onSelect={(pet) => void selectPetSlug(pet)}
                      onAddFavorite={addFavoritePet}
                      onRemoveFavorite={removeFavoritePet}
                    />
                  }
                />
              </SettingsCard>
            </>
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
              <LlmProvidersPanel form={form} onUpdate={(patch) => update(patch)} />

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

          {category === 'data' && <DataSettingsPanel />}
          {category === 'archive' && <ArchiveSettingsPanel />}

        </div>
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
      className={`ds-density-row flex ${
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

function PetMascotSettingPreview({
  enabled,
  selectedSlug,
  selectedName,
  description
}: {
  enabled: boolean
  selectedSlug: string
  selectedName: string
  description: string
}): ReactElement {
  const { t } = useTranslation('settings')
  const [previewSrc, setPreviewSrc] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    let revokePreview: (() => void) | null = null

    setPreviewSrc(null)
    setPreviewError(null)

    if (!selectedSlug) return undefined

    void resolvePetSpritesheetSrc(selectedSlug)
      .then((result) => {
        revokePreview = result.revoke
        if (cancelled) {
          result.revoke()
          return
        }
        setPreviewSrc(result.src)
      })
      .catch(() => {
        if (!cancelled) setPreviewError(t('petMascotPreviewUnavailable'))
      })

    return () => {
      cancelled = true
      revokePreview?.()
    }
  }, [selectedSlug, t])

  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13px] leading-relaxed text-ds-muted">{description}</p>
      <div
        className={`rounded-xl border border-ds-border-muted bg-ds-main/45 p-3 transition dark:bg-white/[0.04] ${
          enabled ? '' : 'opacity-45 grayscale'
        }`}
      >
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="text-[12px] font-semibold text-ds-muted">
            {t('petMascotPreviewTitle')}
          </span>
          <span className="min-w-0 truncate text-right text-[11px] text-ds-faint">
            {selectedName}
          </span>
        </div>
        <div className="flex h-28 items-end justify-center overflow-hidden rounded-lg border border-ds-border-muted bg-ds-card dark:bg-white/[0.06]">
          {previewSrc ? (
            <PetSprite
              src={previewSrc}
              stateId="idle"
              scale={0.42}
              label={selectedName}
              className="pointer-events-none"
            />
          ) : (
            <span className="self-center text-[12px] text-ds-faint">
              {previewError ?? t('petMascotPreviewLoading')}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

function PetMascotSettingsControl({
  enabled,
  selectedSlug,
  favoritePets,
  favoriteCount,
  searchQuery,
  searchResults,
  loading,
  error,
  onEnabledChange,
  onRefresh,
  onSearchQueryChange,
  onSelect,
  onAddFavorite,
  onRemoveFavorite
}: {
  enabled: boolean
  selectedSlug: string
  favoritePets: PetManifestEntry[]
  favoriteCount: number
  searchQuery: string
  searchResults: PetManifestEntry[]
  loading: boolean
  error: string | null
  onEnabledChange: (value: boolean) => void
  onRefresh: () => void
  onSearchQueryChange: (value: string) => void
  onSelect: (pet: PetManifestEntry) => void
  onAddFavorite: (pet: PetManifestEntry) => void
  onRemoveFavorite: (slug: string) => void
}): ReactElement {
  const { t } = useTranslation('settings')
  const [libraryOpen, setLibraryOpen] = useState(false)
  const selectedPet =
    favoritePets.find((pet) => pet.slug === selectedSlug) ??
    (selectedSlug
      ? {
          slug: selectedSlug,
          displayName: selectedSlug,
          kind: 'creature',
          submittedBy: null,
          spritesheetUrl: '',
          petJsonUrl: '',
          zipUrl: null
        }
      : null)
  const selectablePets = selectedPet
    ? [selectedPet, ...favoritePets.filter((pet) => pet.slug !== selectedPet.slug)]
    : favoritePets

  return (
    <div className="flex w-full min-w-0 flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[13px] font-semibold text-ds-ink">{t('petMascotPickTitle')}</div>
          <div className="mt-0.5 text-[12px] leading-5 text-ds-muted">
            {t('petMascotPickDesc')}
          </div>
        </div>
        <Toggle checked={enabled} onChange={onEnabledChange} />
      </div>
      <fieldset
        disabled={!enabled}
        className={`flex min-w-0 flex-col gap-2.5 transition ${
          enabled ? '' : 'pointer-events-none opacity-45 grayscale'
        }`}
      >
        <div className="rounded-xl border border-ds-border bg-ds-card p-3 shadow-sm">
          <label className="block min-w-0">
            <span className="mb-2 flex min-w-0 items-center gap-2">
              <PawPrint className="h-4 w-4 shrink-0 text-accent" strokeWidth={1.8} />
              <div className="min-w-0">
                <span className="block text-[12px] font-medium text-ds-faint">
                  {t('petMascotSelected')}
                </span>
                <span className="block truncate text-[14px] font-semibold text-ds-ink">
                  {selectedPet?.displayName ?? selectedSlug}
                </span>
              </div>
            </span>
            <SettingsSelect
              value={selectedPet?.slug ?? ''}
              disabled={selectablePets.length === 0}
              selectClassName="rounded-lg bg-ds-main focus-within:border-accent/50"
              onChange={(event) => {
                const pet = selectablePets.find((item) => item.slug === event.target.value)
                if (pet) onSelect(pet)
              }}
            >
              {selectablePets.map((pet) => (
                <option key={pet.slug} value={pet.slug}>
                  {pet.displayName} - {pet.slug}
                </option>
              ))}
            </SettingsSelect>
          </label>
        </div>
        <div className="rounded-xl border border-ds-border-muted bg-ds-main/45">
          <button
            type="button"
            onClick={() => setLibraryOpen((open) => !open)}
            className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left transition hover:bg-ds-hover"
          >
            <span className="min-w-0 truncate text-[12px] font-semibold text-ds-muted">
              {t('petMascotSavedTitle')}
            </span>
            <span className="flex shrink-0 items-center gap-2 text-[11px] text-ds-faint">
              <span>{t('petMascotFavoriteCount', { count: favoriteCount })}</span>
              <ChevronDown
                className={`h-3.5 w-3.5 transition ${libraryOpen ? 'rotate-180' : ''}`}
              />
            </span>
          </button>
          {libraryOpen ? (
            <div className="border-t border-ds-border-muted p-2.5">
              {favoritePets.length > 0 ? (
                <div className="mb-2 flex max-h-20 flex-wrap gap-1.5 overflow-y-auto">
                  {favoritePets.map((pet) => {
                    const active = pet.slug === selectedSlug
                    return (
                      <button
                        key={pet.slug}
                        type="button"
                        onClick={() => onRemoveFavorite(pet.slug)}
                        className={`inline-flex max-w-full items-center gap-1 rounded-lg border px-2 py-1 text-[11px] transition ${
                          active
                            ? 'border-accent/35 bg-accent/10 text-accent'
                            : 'border-ds-border bg-ds-card text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
                        }`}
                      >
                        <span className="truncate">{pet.displayName}</span>
                        <X className="h-3 w-3 shrink-0" />
                      </button>
                    )
                  })}
                </div>
              ) : null}
              <input
                value={searchQuery}
                onChange={(event) => onSearchQueryChange(event.target.value)}
                placeholder={t('petMascotSearchPlaceholder')}
                className="w-full rounded-lg border border-ds-border bg-ds-card px-2.5 py-1.5 text-[12px] text-ds-ink placeholder:text-ds-faint focus:border-accent/40 focus:outline-none disabled:cursor-not-allowed"
              />
              {searchResults.length > 0 ? (
                <div className="mt-2 flex max-h-40 flex-col gap-1 overflow-y-auto">
                  {searchResults.map((pet) => (
                    <button
                      key={pet.slug}
                      type="button"
                      disabled={favoriteCount >= 15}
                      onClick={() => onAddFavorite(pet)}
                      className="flex min-w-0 items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12px] text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:cursor-not-allowed disabled:opacity-45"
                    >
                      <PawPrint
                        className="h-3.5 w-3.5 shrink-0 text-ds-faint"
                        strokeWidth={1.8}
                      />
                      <span className="min-w-0 flex-1 truncate text-[13px] font-semibold">
                        {pet.displayName}
                      </span>
                      <span className="shrink-0 text-[11px] text-ds-faint">
                        {favoriteCount >= 15 ? t('petMascotFull') : t('petMascotAdd')}
                      </span>
                    </button>
                  ))}
                </div>
              ) : null}
              <div className="mt-2 flex items-center justify-between gap-3">
                <button
                  type="button"
                  onClick={onRefresh}
                  disabled={loading}
                  className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-ds-border bg-ds-card px-2.5 py-1.5 text-center text-[12px] font-medium leading-none text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:cursor-wait disabled:opacity-60"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
                  {loading ? t('petMascotCachingList') : t('petMascotRefresh')}
                </button>
                {error ? (
                  <span className="min-w-0 truncate text-right text-[12px] text-red-700 dark:text-red-300">
                    {error}
                  </span>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>
      </fieldset>
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
        checked ? 'bg-accent' : 'bg-ds-faint'
      }`}
    >
      <span
        className={`absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition ${
          checked ? 'left-6' : 'left-0.5'
        }`}
      />
    </button>
  )
}

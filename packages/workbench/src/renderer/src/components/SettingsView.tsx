import type { ReactElement, ReactNode } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  mergeClawSettings,
  type ApprovalPolicy,
  type AppSettingsV1,
  type ClawSettingsPatchV1,
  type CustomEndpointV1,
  type EndpointProtocol,
  type SandboxMode
} from '@shared/app-settings'
import {
  Anchor,
  Box,
  ChevronDown,
  ChevronLeft,
  Eye,
  EyeOff,
  FolderOpen,
  Globe,
  Loader2,
  Plug,
  Plus,
  RefreshCw,
  Settings,
  Shield,
  Sparkles,
  CalendarClock,
  PawPrint,
  Pencil,
  Trash2,
  X,
  Zap
} from 'lucide-react'
import type { PetManifestEntry } from '@shared/pet-manifest'
import { applyTheme, applyUiFontScale, applyUiFontFamily } from '../lib/apply-theme'
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
import { normalizeWorkspaceRoot } from '../lib/workspace-path'
import { useChatStore, type SettingsRouteSection } from '../store/chat-store'
import { reloadMcpWithRuntime } from '../lib/settings-reload'
import { McpServersPanel } from './settings/McpServersPanel'
import { PluginsPanel, PluginsPanelHeader } from './settings/PluginsPanel'
import { ClawSettingsPanel } from './settings/ClawSettingsPanel'
import { ModelUsagePanel } from './settings/ModelUsagePanel'
import { settingsBlockButtonClass } from './settings/SettingsActionToolbar'
import { SettingsSelect } from './settings/SettingsSelect'
import { PetSprite } from './pet/PetSprite'
import type { UsageRange } from '@shared/usage-ledger'
import { usePersistentUsage } from '../hooks/use-persistent-usage'

type SettingsCategory = SettingsRouteSection
type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'
type SettingsPatch = Partial<
  Omit<AppSettingsV1, 'deepseek' | 'log' | 'notifications' | 'skills' | 'memory' | 'claw' | 'guiUpdate' | 'customEndpoints'>
> & {
  deepseek?: Partial<AppSettingsV1['deepseek']>
  log?: Partial<AppSettingsV1['log']>
  notifications?: Partial<AppSettingsV1['notifications']>
  skills?: Partial<AppSettingsV1['skills']>
  claw?: ClawSettingsPatchV1
  guiUpdate?: Partial<AppSettingsV1['guiUpdate']>
  customEndpoints?: AppSettingsV1['customEndpoints']
}
type InlineNotice = {
  tone: 'success' | 'error' | 'info'
  message: string
}

const DEFAULT_WORKSPACE_ROOT = '~/.deepseekgui/default_workspace'

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
    customEndpoints: patch.customEndpoints ?? current.customEndpoints,
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
    }
  }
}

export function SettingsView(): ReactElement {
  const { t } = useTranslation('settings')
  const { t: tCommon } = useTranslation('common')
  const setRoute = useChatStore((s) => s.setRoute)
  const settingsSection = useChatStore((s) => s.settingsSection)
  const openSettings = useChatStore((s) => s.openSettings)
  const openInitialSetup = useChatStore((s) => s.openInitialSetup)
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
  const [showApiKey, setShowApiKey] = useState(false)
  const [showRuntimeToken, setShowRuntimeToken] = useState(false)
  const [tokenFingerprint, setTokenFingerprint] = useState('')
  const [tokenRegenBusy, setTokenRegenBusy] = useState(false)
  const [tokenRegenError, setTokenRegenError] = useState<string | null>(null)
  const [logPath, setLogPath] = useState('')
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
  const [skillNotice, setSkillNotice] = useState<InlineNotice | null>(null)
  const [installedSkills, setInstalledSkills] = useState<Array<{ id: string; name: string; path: string }>>([])
  const [skillsListLoading, setSkillsListLoading] = useState(false)
  const [deepseekPaths, setDeepseekPaths] = useState({
    configPath: '~/.deepseek/config.toml',
    mcpPath: '~/.deepseek/mcp.json',
    hooksDir: '~/.deepseek/hooks',
    skillsDir: '~/.deepseek/skills'
  })
  const [mcpConfigPath, setMcpConfigPath] = useState('~/.deepseek/mcp.json')
  const [mcpConfigText, setMcpConfigText] = useState('')
  const [mcpConfigExists, setMcpConfigExists] = useState(false)
  const [mcpLoading, setMcpLoading] = useState(false)
  const [mcpLoaded, setMcpLoaded] = useState(false)
  const [mcpBusy, setMcpBusy] = useState(false)
  const [mcpNotice, setMcpNotice] = useState<InlineNotice | null>(null)
  const [hooksNotice, setHooksNotice] = useState<InlineNotice | null>(null)
  const initializedCategory = useRef(false)
  const saveTimer = useRef<ReturnType<typeof window.setTimeout> | null>(null)
  const statusTimer = useRef<ReturnType<typeof window.setTimeout> | null>(null)
  const draftVersion = useRef(0)
  const formTheme = form?.theme
  const formUiFontScale = form?.uiFontScale
  const formUiFontFamily = form?.uiFontFamily
  const formWorkspaceRoot = form?.workspaceRoot
  const formPort = form?.deepseek.port
  const formDeepseekBinaryPath = form?.deepseek.binaryPath ?? ''

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

  const loadPetCatalog = useCallback(async (): Promise<void> => {
    if (typeof window.dsGui?.fetchPetManifest !== 'function') return
    setPetCatalogLoading(true)
    setPetCatalogError(null)
    try {
      const result = await window.dsGui.fetchPetManifest()
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
          setMcpConfigPath(paths.mcpPath)
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

  useEffect(() => {
    if (typeof window.dsGui?.getLogPath !== 'function') return
    void window.dsGui.getLogPath().then((p) => setLogPath(p))
  }, [category])

  // Display the cached runtime-token fingerprint when entering general settings.
  useEffect(() => {
    if (category !== 'general') return
    if (typeof window.dsGui?.getRuntimeTokenFingerprint !== 'function') return
    let cancelled = false
    void window.dsGui
      .getRuntimeTokenFingerprint()
      .then((res) => {
        if (!cancelled) setTokenFingerprint(res.fingerprint)
      })
      .catch(() => {
        /* best-effort; field falls back to "auto-managed" copy */
      })
    return () => {
      cancelled = true
    }
  }, [category])

  useEffect(() => {
    if (!form || initializedCategory.current) return
    initializedCategory.current = true
    const hasCustomKey = form.customEndpoints.some(
      (endpoint) => endpoint.enabled && endpoint.apiKey.trim()
    )
    if (!form.deepseek.apiKey?.trim() && !hasCustomKey) {
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

  const handleRegenerateRuntimeToken = async (): Promise<void> => {
    if (typeof window.dsGui?.regenerateRuntimeToken !== 'function') return
    setTokenRegenBusy(true)
    setTokenRegenError(null)
    try {
      const result = await window.dsGui.regenerateRuntimeToken()
      if (result.ok) {
        setTokenFingerprint(result.fingerprint)
        // Drop any explicit override so the runtime continues reading the
        // (now-rotated) token file rather than a stale settings value.
        update({ deepseek: { runtimeToken: '' } })
      } else {
        setTokenRegenError(result.message)
      }
    } catch (e) {
      setTokenRegenError(e instanceof Error ? e.message : String(e))
    } finally {
      setTokenRegenBusy(false)
    }
  }

  const loadMcpConfig = async (): Promise<void> => {
    if (typeof window.dsGui?.getMcpConfigFile !== 'function') return
    setMcpLoading(true)
    setMcpNotice(null)
    try {
      const config = await window.dsGui.getMcpConfigFile()
      setMcpConfigPath(config.path)
      setMcpConfigText(config.content)
      setMcpConfigExists(config.exists)
      setMcpLoaded(true)
    } catch (e) {
      setMcpNotice({
        tone: 'error',
        message: e instanceof Error ? e.message : String(e)
      })
    } finally {
      setMcpLoading(false)
    }
  }

  useEffect(() => {
    if (category !== 'mcp' || mcpLoaded || mcpLoading) return
    void loadMcpConfig()
  }, [category, mcpLoaded, mcpLoading])

  const loadInstalledPlugins = async (): Promise<void> => {
    const root = deepseekPaths.skillsDir
    if (!root || typeof window.dsGui?.listSkillsInRoot !== 'function') return
    setSkillsListLoading(true)
    try {
      const result = await window.dsGui.listSkillsInRoot(root)
      setInstalledSkills(result.ok ? result.skills : [])
    } finally {
      setSkillsListLoading(false)
    }
  }

  useEffect(() => {
    if (category !== 'skill') return
    void loadInstalledPlugins()
  }, [category, deepseekPaths.skillsDir])

  const openPluginsDir = async (): Promise<void> => {
    const root = deepseekPaths.skillsDir
    if (!root || typeof window.dsGui?.openSkillRoot !== 'function') return
    setSkillNotice(null)
    const result = await window.dsGui.openSkillRoot(root)
    if (!result.ok) {
      setSkillNotice({ tone: 'error', message: result.message ?? t('applyFailed') })
    }
  }

  const reloadMcpSettings = async (): Promise<void> => {
    setMcpLoading(true)
    try {
      const result = await reloadMcpWithRuntime(loadMcpConfig)
      if (result.runtime) {
        setMcpNotice({ tone: 'success', message: t('mcpReloadRuntimeOk') })
      } else {
        setMcpNotice({ tone: 'info', message: t('mcpReloadDiskOnly') })
      }
    } catch (e) {
      setMcpNotice({
        tone: 'error',
        message: e instanceof Error ? e.message : String(e)
      })
    } finally {
      setMcpLoading(false)
    }
  }

  const saveMcpConfig = async (content?: string, quiet = false): Promise<void> => {
    if (typeof window.dsGui?.setMcpConfigFile !== 'function') return
    const payload = content ?? mcpConfigText
    setMcpBusy(true)
    if (!quiet) setMcpNotice(null)
    try {
      const result = await window.dsGui.setMcpConfigFile(payload)
      setMcpConfigText(payload)
      setMcpConfigPath(result.path)
      setMcpConfigExists(true)
      if (!quiet) {
        setMcpNotice({
          tone: 'success',
          message: t('mcpSaved', { path: result.path })
        })
      }
    } catch (e) {
      setMcpNotice({
        tone: 'error',
        message: e instanceof Error ? e.message : String(e)
      })
    } finally {
      setMcpBusy(false)
    }
  }

  const openMcpConfigDir = async (): Promise<void> => {
    if (typeof window.dsGui?.openMcpConfigDir !== 'function') return
    const result = await window.dsGui.openMcpConfigDir()
    if (!result.ok) {
      setMcpNotice({ tone: 'error', message: result.message ?? t('applyFailed') })
    }
  }

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

  const openOnboardingPreview = (): void => {
    void (async () => {
      await flushPendingSave()
      openInitialSetup('preview')
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

  const corsValue = (form.deepseek.extraCorsOrigins ?? []).join(', ')

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
    `flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-[14px] font-medium transition ${
      category === c
        ? 'bg-ds-subtle text-ds-ink shadow-sm ring-1 ring-ds-border-muted'
        : 'text-ds-muted hover:bg-ds-hover'
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
          <button type="button" className={catCls('models')} onClick={() => openSettings('models')}>
            <Box className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
            {t('models')}
          </button>
          <button type="button" className={catCls('mcp')} onClick={() => openSettings('mcp')}>
            <Plug className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
            {t('mcp')}
          </button>
          <button type="button" className={catCls('skill')} onClick={() => openSettings('skill')}>
            <Sparkles className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
            {t('skill')}
          </button>
          <button type="button" className={catCls('hooks')} onClick={() => openSettings('hooks')}>
            <Anchor className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
            {t('hooks')}
          </button>
          <button type="button" className={catCls('claw')} onClick={() => openSettings('claw')}>
            <CalendarClock className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
            {t('claw')}
          </button>
          <button type="button" className={catCls('permissions')} onClick={() => openSettings('permissions')}>
            <Shield className="h-4 w-4 shrink-0 opacity-70" strokeWidth={1.75} />
            {t('permissions')}
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

      <div className="ds-page-scroll ds-no-drag min-h-0 min-w-0 flex-1 overflow-y-auto px-10 py-10">
        <div className="mx-auto max-w-3xl">
          {!form.deepseek.apiKey.trim() && category === 'models' ? (
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
                {category === 'models' ? t('models') : t('title')}
              </h1>
              <p className="mt-1 text-[14px] text-ds-muted">{t('subtitle')}</p>
            </div>
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
                  title={t('theme')}
                  description={t('themeDesc')}
                  control={
                    <SettingsSelect
                      value={form.theme}
                      onChange={(e) => update({ theme: e.target.value as AppSettingsV1['theme'] })}
                    >
                      <option value="system">{t('themeSystem')}</option>
                      <option value="light">{t('themeLight')}</option>
                      <option value="dark">{t('themeDark')}</option>
                    </SettingsSelect>
                  }
                />
                <SettingRow
                  title={t('onboardingPreview')}
                  description={t('onboardingPreviewDesc')}
                  control={
                    <button
                      type="button"
                      onClick={openOnboardingPreview}
                      className={`${settingsBlockButtonClass()} text-[14px]`}
                    >
                      {t('onboardingPreviewOpen')}
                    </button>
                  }
                />
                <SettingRow
                  title={t('fontScale')}
                  description={t('fontScaleDesc')}
                  control={
                    <SettingsSelect
                      value={form.uiFontScale}
                      onChange={(e) =>
                        update({
                          uiFontScale: e.target.value as AppSettingsV1['uiFontScale']
                        })
                      }
                    >
                      <option value="small">{t('fontScaleSmall')}</option>
                      <option value="medium">{t('fontScaleMedium')}</option>
                      <option value="large">{t('fontScaleLarge')}</option>
                    </SettingsSelect>
                  }
                />
                <SettingRow
                  title={t('fontFamily')}
                  description={t('fontFamilyDesc')}
                  control={
                    <SettingsSelect
                      value={form.uiFontFamily}
                      onChange={(e) =>
                        update({
                          uiFontFamily: e.target.value as AppSettingsV1['uiFontFamily']
                        })
                      }
                    >
                      <option value="inter-noto">{t('fontFamilyInterNoto')}</option>
                      <option value="system-native">{t('fontFamilySystemNative')}</option>
                    </SettingsSelect>
                  }
                />
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
                      onRefresh={() => void loadPetCatalog()}
                      onSearchQueryChange={setPetCatalogQuery}
                      onSelect={(pet) => void selectPetSlug(pet)}
                      onAddFavorite={addFavoritePet}
                      onRemoveFavorite={removeFavoritePet}
                    />
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
                  layout="stacked"
                  title={t('workspaceRoot')}
                  description={t('workspaceRootDesc')}
                  control={
                    <div className="flex w-full min-w-0 flex-col gap-2">
                      <div className="grid w-full gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start sm:gap-4">
                        <input
                          className="w-full min-w-0 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[14px] text-ds-ink shadow-sm focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30"
                          value={form.workspaceRoot}
                          onChange={(e) => update({ workspaceRoot: e.target.value })}
                          placeholder={t('workspaceRootPlaceholder')}
                          title={form.workspaceRoot}
                        />
                        <div className="flex flex-col gap-2 sm:min-w-[8.5rem]">
                          <button
                            type="button"
                            onClick={resetWorkspaceToDefault}
                            className={settingsBlockButtonClass()}
                          >
                            {t('restoreWorkspaceDefault')}
                          </button>
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
                  }
                />
              </SettingsCard>

              <SettingsCard title={t('sectionRuntime')} className="mt-6">
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
                  title={t('deepseekBinary')}
                  description={t('deepseekBinaryHint')}
                  controlWidth="medium"
                  control={
                    <input
                      className="w-full min-w-0 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[14px] text-ds-ink shadow-sm focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30"
                      placeholder={t('deepseekBinaryPlaceholder')}
                      value={form.deepseek.binaryPath}
                      onChange={(e) => update({ deepseek: { binaryPath: e.target.value } })}
                    />
                  }
                />
                <SettingRow
                  title={t('runtimeToken')}
                  description={t('runtimeTokenDesc')}
                  controlWidth="medium"
                  control={
                    <div className="flex w-full flex-col gap-2">
                      <input
                        type="text"
                        readOnly
                        className="w-full rounded-xl border border-ds-border bg-ds-card px-3 py-2 font-mono text-[12px] text-ds-ink/70 shadow-sm focus:outline-none"
                        value={
                          tokenFingerprint ||
                          (form.deepseek.runtimeToken
                            ? `${form.deepseek.runtimeToken.slice(0, 8)}…${form.deepseek.runtimeToken.slice(-4)}`
                            : t('runtimeTokenAutoManaged'))
                        }
                        aria-label={t('runtimeToken')}
                      />
                      <button
                        type="button"
                        disabled={tokenRegenBusy}
                        className="inline-flex items-center justify-center gap-1.5 self-start rounded-md border border-ds-border px-2 py-1 text-center text-[12px] leading-none hover:border-accent/40 disabled:cursor-not-allowed disabled:opacity-55"
                        onClick={() => void handleRegenerateRuntimeToken()}
                      >
                        {tokenRegenBusy ? (
                          <Loader2 className="h-3 w-3 animate-spin" strokeWidth={2} />
                        ) : null}
                        {t('runtimeTokenRegenerate')}
                      </button>
                      {tokenRegenError ? (
                        <p className="text-[12px] text-red-700 dark:text-red-300">{tokenRegenError}</p>
                      ) : null}
                    </div>
                  }
                />
                <SettingRow
                  title={t('corsOrigins')}
                  description={t('corsOriginsDesc')}
                  controlWidth="medium"
                  control={
                    <input
                      className="w-full min-w-0 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[14px] text-ds-ink shadow-sm focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30"
                      value={corsValue}
                      onChange={(e) =>
                        update({
                          deepseek: {
                            extraCorsOrigins: e.target.value
                              .split(',')
                              .map((s) => s.trim())
                              .filter(Boolean)
                          }
                        })
                      }
                    />
                  }
                />
              </SettingsCard>

              <SettingsCard title={t('logTitle')} className="mt-6">
                <SettingRow
                  title={t('logEnabled')}
                  description={t('logEnabledDesc')}
                  control={
                    <Toggle
                      checked={form.log.enabled}
                      onChange={(v) => update({ log: { enabled: v } })}
                    />
                  }
                />
                <SettingRow
                  title={t('logRetention')}
                  description={t('logRetentionDesc')}
                  control={
                    <SettingsSelect
                      value={form.log.retentionDays}
                      onChange={(e) =>
                        update({ log: { retentionDays: Number(e.target.value) } })
                      }
                    >
                      <option value={1}>{t('logRetentionOne')}</option>
                      <option value={2}>{t('logRetentionTwo')}</option>
                      <option value={3}>{t('logRetentionThree')}</option>
                      <option value={5}>{t('logRetentionFive')}</option>
                      <option value={7}>{t('logRetentionSeven')}</option>
                    </SettingsSelect>
                  }
                />
                <SettingRow
                  relaxed
                  title={t('logDir')}
                  description={t('logDirDesc')}
                  controlWidth="medium"
                  control={
                    <div className="flex w-full flex-col items-end gap-2">
                      {logPath ? (
                        <code
                          className="block w-full max-w-[280px] truncate rounded-xl bg-ds-main/70 px-3 py-2 font-mono text-[12px] text-ds-muted shadow-sm"
                          title={logPath}
                        >
                          {logPath}
                        </code>
                      ) : (
                        <span className="text-[13px] text-ds-faint">…</span>
                      )}
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
            </>
          )}

          {category === 'models' && (
            <>
              <SettingsCard title={t('sectionModels')}>
                  <SettingRow
                    title={t('configFilePath')}
                    description={t('configFilePathDesc')}
                    controlWidth="medium"
                    control={
                      <div className="w-full min-w-0 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[13px] text-ds-muted shadow-sm">
                        <code className="block break-all rounded-lg bg-ds-main/70 px-2 py-1 font-mono text-[12px] text-ds-ink">
                          {deepseekPaths.configPath}
                        </code>
                      </div>
                    }
                  />
                  <SettingRow
                    title={t('apiKey')}
                    description={t('apiKeyDesc')}
                    controlWidth="medium"
                    control={
                      <SecretInput
                        value={form.deepseek.apiKey}
                        onChange={(value) => update({ deepseek: { apiKey: value } })}
                        visible={showApiKey}
                        onToggleVisibility={() => setShowApiKey((value) => !value)}
                        placeholder="sk-…"
                        autoComplete="off"
                        invalid={!form.deepseek.apiKey.trim()}
                        showLabel={t('showSecret')}
                        hideLabel={t('hideSecret')}
                      />
                    }
                  />
                  <SettingRow
                    title={t('baseUrl')}
                    description={t('baseUrlDesc')}
                    controlWidth="medium"
                    control={
                      <input
                        className="w-full min-w-0 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[14px] text-ds-ink shadow-sm focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30"
                        placeholder={t('baseUrlPlaceholder')}
                        value={form.deepseek.baseUrl}
                        onChange={(e) => update({ deepseek: { baseUrl: e.target.value } })}
                      />
                    }
                  />
                </SettingsCard>

                <SettingsCard title={t('customEndpoints')} className="mt-6">
                  <CustomEndpointsPanel
                    endpoints={form.customEndpoints}
                    onUpdate={(patch) => update(patch)}
                  />
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
            <SettingsCard title={t('permissions')}>
              <SettingRow
                title={t('approvalPolicy')}
                description={t('approvalPolicyDesc')}
                control={
                  <SettingsSelect
                    value={form.deepseek.approvalPolicy}
                    onChange={(e) =>
                      update({
                        deepseek: {
                          approvalPolicy: e.target.value as ApprovalPolicy
                        }
                      })
                    }
                  >
                    <option value="auto">{t('approvalAuto')}</option>
                    <option value="on-request">{t('approvalOnRequest')}</option>
                    <option value="untrusted">{t('approvalUntrusted')}</option>
                    <option value="suggest">{t('approvalSuggest')}</option>
                    <option value="never">{t('approvalNever')}</option>
                  </SettingsSelect>
                }
              />
              <SettingRow
                title={t('sandboxMode')}
                description={t('sandboxModeDesc')}
                control={
                  <SettingsSelect
                    value={form.deepseek.sandboxMode}
                    onChange={(e) =>
                      update({
                        deepseek: {
                          sandboxMode: e.target.value as SandboxMode
                        }
                      })
                    }
                  >
                    <option value="workspace-write">{t('sandboxWorkspaceWrite')}</option>
                    <option value="read-only">{t('sandboxReadOnly')}</option>
                    <option value="danger-full-access">{t('sandboxFullAccess')}</option>
                    <option value="external-sandbox">{t('sandboxExternal')}</option>
                  </SettingsSelect>
                }
              />
            </SettingsCard>
          )}

          {category === 'skill' && (
                <SettingsCard title={t('skill')}>
                  <div className="px-4 py-5">
                    <h3 className="text-[14px] font-semibold text-ds-ink">{t('pluginsInstalled')}</h3>
                    <PluginsPanelHeader />
                    <div className="mt-4 w-full min-w-0">
                      <PluginsPanel
                        showIntro={false}
                        skillsDir={deepseekPaths.skillsDir}
                        plugins={installedSkills}
                        loading={skillsListLoading}
                        onReload={() => void loadInstalledPlugins()}
                        onOpenSkillsDir={() => void openPluginsDir()}
                      />
                      {skillNotice ? (
                        <div className="mt-3">
                          <InlineNoticeView notice={skillNotice} />
                        </div>
                      ) : null}
                    </div>
                  </div>
                </SettingsCard>
          )}

          {category === 'mcp' && (
                <SettingsCard title={t('mcp')}>
                  <div className="px-4 py-5">
                    <h3 className="text-[14px] font-semibold text-ds-ink">{t('mcpInstalled')}</h3>
                    <p className="mt-1 max-w-3xl text-[13px] leading-6 text-ds-muted">{t('mcpPathDesc')}</p>
                    <div className="mt-4 w-full min-w-0">
                      <McpServersPanel
                        configPath={mcpConfigPath}
                        configText={mcpConfigText}
                        configExists={mcpConfigExists}
                        loading={mcpLoading}
                        busy={mcpBusy}
                        notice={mcpNotice}
                        onConfigTextChange={setMcpConfigText}
                        onReload={() => void reloadMcpSettings()}
                        onSave={(content, quiet) => void saveMcpConfig(content, quiet)}
                        onOpenConfigFolder={() => void openMcpConfigDir()}
                      />
                    </div>
                  </div>
                </SettingsCard>
          )}

          {category === 'claw' && form ? (
            <ClawSettingsPanel
              form={form}
              onClawPatch={(patch) => update({ claw: patch })}
            />
          ) : null}

          {category === 'hooks' && (
            <SettingsCard title={t('hooks')}>
              <SettingRow
                relaxed
                alignControl="center"
                title={t('hooksConfigPath')}
                description={
                  <>
                    <p className="text-[13px] leading-6 text-ds-muted">{t('hooksConfigPathDesc')}</p>
                    <p className="text-[13px] leading-6 text-ds-muted">{t('hooksDesc')}</p>
                  </>
                }
                controlWidth="medium"
                control={
                  <div
                    className="w-full max-w-[280px] rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[13px] text-ds-muted shadow-sm"
                    title={`${deepseekPaths.configPath} · [hooks]\n${deepseekPaths.hooksDir}`}
                  >
                    <code className="block truncate rounded-lg bg-ds-main/70 px-2 py-1 font-mono text-[12px] text-ds-ink">
                      {deepseekPaths.configPath} · [hooks]
                    </code>
                    <span className="mt-1.5 block truncate text-[11px] text-ds-faint">
                      {deepseekPaths.hooksDir}
                    </span>
                  </div>
                }
              />
              <SettingRow
                relaxed
                alignControl="center"
                title={t('hooksActions')}
                description={
                  <>
                    <p className="text-[13px] leading-6 text-ds-muted">{t('hooksActionsDesc')}</p>
                    <p className="text-[13px] leading-6 text-ds-faint">{t('hooksOpenConfigHint')}</p>
                  </>
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
  control,
  wideControl = false,
  relaxed = false,
  layout = 'default',
  alignControl = 'start',
  controlWidth = 'compact'
}: {
  title: string
  description?: ReactNode
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

  if (layout === 'stacked') {
    return (
      <div className="flex flex-col gap-4 px-4 py-5">
        <div className="min-w-0">
          <div className="text-[14px] font-semibold text-ds-ink">{title}</div>
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
      className={`flex ${
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
        <div className="text-[14px] font-semibold text-ds-ink">{title}</div>
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
        className={`rounded-xl border border-ds-border-muted bg-ds-main/45 p-3 transition ${
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
        <div className="flex h-28 items-end justify-center overflow-hidden rounded-lg border border-ds-border-muted bg-ds-card">
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

function CustomEndpointsPanel({
  endpoints,
  onUpdate
}: {
  endpoints: CustomEndpointV1[]
  onUpdate: (patch: SettingsPatch) => void
}): ReactElement {
  const { t } = useTranslation('settings')
  const bumpUsageRefreshKey = (): void => {
    useChatStore.setState((state) => ({ usageRefreshKey: state.usageRefreshKey + 1 }))
  }
  const [showAdd, setShowAdd] = useState(false)
  const [addName, setAddName] = useState('')
  const [addUrl, setAddUrl] = useState('')
  const [addKey, setAddKey] = useState('')
  const [addProtocol, setAddProtocol] = useState<EndpointProtocol>('openai')
  const [modelDrafts, setModelDrafts] = useState<Record<string, string>>({})
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; message: string; testing: boolean }>>({})
  const [editingEndpointId, setEditingEndpointId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editUrl, setEditUrl] = useState('')
  const [editKey, setEditKey] = useState('')
  const [editProtocol, setEditProtocol] = useState<EndpointProtocol>('openai')
  const [showEditKey, setShowEditKey] = useState(false)

  const cancelEndpointEdit = (): void => {
    setEditingEndpointId(null)
    setEditName('')
    setEditUrl('')
    setEditKey('')
    setEditProtocol('openai')
    setShowEditKey(false)
  }

  const startEndpointEdit = (endpoint: CustomEndpointV1): void => {
    setShowAdd(false)
    setEditingEndpointId(endpoint.id)
    setEditName(endpoint.name)
    setEditUrl(endpoint.baseUrl)
    setEditKey(endpoint.apiKey)
    setEditProtocol(endpoint.protocol)
    setShowEditKey(false)
  }

  const saveEndpointEdit = (index: number): void => {
    if (!editName.trim() || !editUrl.trim() || !editKey.trim()) return
    updateEndpoints(
      endpoints.map((endpoint, i) =>
        i === index
          ? {
              ...endpoint,
              name: editName.trim(),
              protocol: editProtocol,
              baseUrl: editUrl.trim(),
              apiKey: editKey.trim()
            }
          : endpoint
      )
    )
    cancelEndpointEdit()
  }

  const updateEndpoints = (next: CustomEndpointV1[]): void => {
    onUpdate({ customEndpoints: next })
  }

  const handleAdd = (): void => {
    if (!addName.trim() || !addUrl.trim() || !addKey.trim()) return
    const slug = addName.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'endpoint'
    const usedIds = new Set(['deepseek', ...endpoints.map((endpoint) => endpoint.id)])
    let id = slug
    let suffix = 2
    while (usedIds.has(id)) {
      id = `${slug}-${suffix}`
      suffix += 1
    }
    const newEndpoint: CustomEndpointV1 = {
      id,
      name: addName.trim(),
      protocol: addProtocol,
      baseUrl: addUrl.trim(),
      apiKey: addKey.trim(),
      enabled: true,
      models: []
    }
    updateEndpoints([...endpoints, newEndpoint])
    setAddName('')
    setAddUrl('')
    setAddKey('')
    setAddProtocol('openai')
    setShowAdd(false)
  }

  const handleRemove = (index: number): void => {
    const removed = endpoints[index]
    if (removed) {
      if (editingEndpointId === removed.id) cancelEndpointEdit()
      void window.dsGui.pruneUsageProvider(removed.id).finally(bumpUsageRefreshKey)
    }
    updateEndpoints(endpoints.filter((_, i) => i !== index))
  }

  const handleToggleEndpoint = (index: number): void => {
    updateEndpoints(
      endpoints.map((endpoint, i) =>
        i === index ? { ...endpoint, enabled: !endpoint.enabled } : endpoint
      )
    )
  }

  const handleTest = async (ep: CustomEndpointV1, modelId: string): Promise<boolean> => {
    const key = `${ep.id}::${modelId}`
    setTestResults((prev) => ({ ...prev, [key]: { ok: false, message: '正在测试...', testing: true } }))
    try {
      const result = await window.dsGui.testEndpoint(ep.protocol, ep.baseUrl, ep.apiKey, modelId)
      setTestResults((prev) => ({ ...prev, [key]: { ok: result.ok, message: result.message, testing: false } }))
      return result.ok
    } catch (e) {
      setTestResults((prev) => ({
        ...prev,
        [key]: { ok: false, message: e instanceof Error ? e.message : String(e), testing: false }
      }))
      return false
    }
  }

  const handleAddModel = async (index: number): Promise<void> => {
    const endpoint = endpoints[index]
    const modelId = (modelDrafts[endpoint.id] ?? '').trim()
    if (!modelId || endpoint.models.some((model) => model.id === modelId)) return
    const passed = await handleTest(endpoint, modelId)
    const now = new Date().toISOString()
    updateEndpoints(
      endpoints.map((item, i) =>
        i === index
          ? {
              ...item,
              models: [
                ...item.models,
                {
                  id: modelId,
                  enabled: true,
                  testStatus: passed ? 'passed' as const : 'failed' as const,
                  toolCalling: passed,
                  lastTestedAt: now
                }
              ]
            }
          : item
      )
    )
    setModelDrafts((prev) => ({ ...prev, [endpoint.id]: '' }))
  }

  const handleRetestModel = async (index: number, modelId: string): Promise<void> => {
    const endpoint = endpoints[index]
    const passed = await handleTest(endpoint, modelId)
    updateEndpoints(
      endpoints.map((item, endpointIndex) =>
        endpointIndex === index
          ? {
              ...item,
              models: item.models.map((model) =>
                model.id === modelId
                  ? {
                      ...model,
                      testStatus: passed ? 'passed' as const : 'failed' as const,
                      toolCalling: passed,
                      lastTestedAt: new Date().toISOString()
                    }
                  : model
              )
            }
          : item
      )
    )
  }

  const handleRemoveModel = (endpointIndex: number, modelId: string): void => {
    const endpoint = endpoints[endpointIndex]
    if (endpoint) {
      void window.dsGui
        .pruneUsageEndpointModel(endpoint.id, modelId)
        .finally(bumpUsageRefreshKey)
    }
    updateEndpoints(
      endpoints.map((item, index) =>
        index === endpointIndex
          ? { ...item, models: item.models.filter((model) => model.id !== modelId) }
          : item
      )
    )
  }

  return (
    <div className="px-4 py-5">
      <p className="mb-4 text-[13px] leading-6 text-ds-muted">
        {t('customEndpointsDesc')}
      </p>

      {endpoints.map((ep, index) => {
        const isEditing = editingEndpointId === ep.id
        return (
        <div key={ep.id} className="mb-3 rounded-xl border border-ds-border bg-ds-card p-4 shadow-sm">
          {isEditing ? (
            <div className="flex flex-col gap-3">
              <h4 className="text-[14px] font-semibold text-ds-ink">{t('editEndpointTitle')}</h4>
              <div className="grid grid-cols-2 gap-3">
                <input
                  className="rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[13px] text-ds-ink shadow-sm focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30"
                  placeholder={t('endpointNamePlaceholder')}
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                />
                <select
                  className="rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[13px] text-ds-ink shadow-sm focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30"
                  value={editProtocol}
                  onChange={(e) => setEditProtocol(e.target.value as EndpointProtocol)}
                >
                  <option value="openai">OpenAI compatible</option>
                  <option value="anthropic">Anthropic compatible</option>
                </select>
              </div>
              <input
                className="rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[13px] text-ds-ink shadow-sm focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30"
                placeholder={t('endpointUrlPlaceholder')}
                value={editUrl}
                onChange={(e) => setEditUrl(e.target.value)}
              />
              <SecretInput
                value={editKey}
                onChange={setEditKey}
                visible={showEditKey}
                onToggleVisibility={() => setShowEditKey((value) => !value)}
                placeholder={t('endpointKeyPlaceholder')}
                autoComplete="off"
                showLabel={t('showSecret')}
                hideLabel={t('hideSecret')}
              />
              <div className="flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={cancelEndpointEdit}
                  className="rounded-xl border border-ds-border px-3 py-1.5 text-[13px] font-medium text-ds-muted hover:bg-ds-hover"
                >
                  {t('cancelBtn')}
                </button>
                <button
                  type="button"
                  onClick={() => saveEndpointEdit(index)}
                  disabled={!editName.trim() || !editUrl.trim() || !editKey.trim()}
                  className="rounded-xl bg-ds-userbubble px-3 py-1.5 text-[13px] font-medium text-ds-userbubbleFg disabled:opacity-50"
                >
                  {t('saveEndpointBtn')}
                </button>
              </div>
            </div>
          ) : (
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-[14px] font-semibold text-ds-ink">{ep.name}</span>
                <span className="rounded-full bg-ds-hover px-2 py-0.5 text-[10px] font-medium uppercase text-ds-muted">
                  {ep.protocol}
                </span>
                <span className={`text-[11px] ${ep.enabled ? 'text-emerald-600' : 'text-ds-faint'}`}>
                  {ep.enabled ? t('endpointEnabled') : t('endpointDisabled')}
                </span>
              </div>
              <div className="mt-1 truncate font-mono text-[12px] text-ds-muted" title={ep.baseUrl}>
                {ep.baseUrl}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <button
                type="button"
                onClick={() => startEndpointEdit(ep)}
                className="inline-flex items-center gap-1 rounded-lg border border-ds-border px-2 py-1 text-[12px] text-ds-muted hover:bg-ds-hover"
              >
                <Pencil className="h-3 w-3" strokeWidth={2} />
                {t('editEndpointBtn')}
              </button>
              <button
                type="button"
                onClick={() => handleToggleEndpoint(index)}
                className="rounded-lg border border-ds-border px-2 py-1 text-[12px] text-ds-muted hover:bg-ds-hover"
              >
                {ep.enabled ? t('disableEndpointBtn') : t('enableEndpointBtn')}
              </button>
              <button
                type="button"
                onClick={() => handleRemove(index)}
                className="rounded-lg border border-ds-border p-1 text-ds-muted hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/30"
              >
                <Trash2 className="h-3.5 w-3.5" strokeWidth={2} />
              </button>
            </div>
          </div>
          )}

          {!isEditing ? (
          <div className="mt-4 space-y-2">
            {ep.models.map((model) => {
              const testKey = `${ep.id}::${model.id}`
              const test = testResults[testKey]
              return (
                <div key={model.id} className="rounded-lg border border-ds-border-muted bg-ds-hover/30 px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-ds-ink">{model.id}</span>
                    <span className={`text-[10px] ${model.testStatus === 'passed' ? 'text-emerald-600' : model.testStatus === 'failed' ? 'text-red-600' : 'text-ds-faint'}`}>
                      {model.testStatus === 'passed' ? t('modelTestPassed') : model.testStatus === 'failed' ? t('modelTestFailed') : t('modelUntested')}
                    </span>
                    <button
                      type="button"
                      disabled={test?.testing}
                      onClick={() => void handleRetestModel(index, model.id)}
                      className="inline-flex items-center gap-1 rounded-md border border-ds-border px-2 py-0.5 text-[11px] text-ds-muted disabled:opacity-50"
                    >
                      {test?.testing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Zap className="h-3 w-3" />}
                      {t('testBtn')}
                    </button>
                    <button type="button" onClick={() => handleRemoveModel(index, model.id)} className="text-ds-faint hover:text-red-600">
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  {test && !test.testing ? (
                    <div className={`mt-1 text-[11px] ${test.ok ? 'text-emerald-700' : 'text-red-700'}`}>
                      {test.message}
                    </div>
                  ) : null}
                </div>
              )
            })}
            <div className="flex gap-2">
              <input
                className="min-w-0 flex-1 rounded-lg border border-ds-border bg-ds-card px-3 py-1.5 font-mono text-[12px] text-ds-ink"
                placeholder={t('endpointModelPlaceholder')}
                value={modelDrafts[ep.id] ?? ''}
                onChange={(event) => setModelDrafts((prev) => ({ ...prev, [ep.id]: event.target.value }))}
              />
              <button
                type="button"
                disabled={!(modelDrafts[ep.id] ?? '').trim()}
                onClick={() => void handleAddModel(index)}
                className="rounded-lg bg-ds-userbubble px-3 py-1.5 text-[12px] font-medium text-ds-userbubbleFg disabled:opacity-50"
              >
                {t('testAndAddModelBtn')}
              </button>
            </div>
          </div>
          ) : null}
        </div>
        )
      })}

      {showAdd ? (
        <div className="mt-3 rounded-xl border border-accent/30 bg-ds-card p-4 shadow-sm">
          <h4 className="mb-3 text-[14px] font-semibold text-ds-ink">
            {t('addEndpointTitle')}
          </h4>
          <div className="flex flex-col gap-3">
            <div className="grid grid-cols-2 gap-3">
              <input
                className="rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[13px] text-ds-ink shadow-sm focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30"
                placeholder={t('endpointNamePlaceholder')}
                value={addName}
                onChange={(e) => setAddName(e.target.value)}
              />
              <select
                className="rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[13px] text-ds-ink shadow-sm focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30"
                value={addProtocol}
                onChange={(e) => setAddProtocol(e.target.value as EndpointProtocol)}
              >
                <option value="openai">OpenAI compatible</option>
                <option value="anthropic">Anthropic compatible</option>
              </select>
            </div>
            <input
              className="rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[13px] text-ds-ink shadow-sm focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30"
              placeholder={t('endpointUrlPlaceholder')}
              value={addUrl}
              onChange={(e) => setAddUrl(e.target.value)}
            />
            <input
              type="password"
              className="rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[13px] text-ds-ink shadow-sm focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30"
              placeholder={t('endpointKeyPlaceholder')}
              value={addKey}
              onChange={(e) => setAddKey(e.target.value)}
            />
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  cancelEndpointEdit()
                  setShowAdd(false)
                  setAddName('')
                  setAddUrl('')
                  setAddKey('')
                  setAddProtocol('openai')
                }}
                className="rounded-xl border border-ds-border px-3 py-1.5 text-[13px] font-medium text-ds-muted hover:bg-ds-hover"
              >
                {t('cancelBtn')}
              </button>
              <button
                type="button"
                onClick={handleAdd}
                disabled={!addName.trim() || !addUrl.trim() || !addKey.trim()}
                className="rounded-xl bg-ds-userbubble px-3 py-1.5 text-[13px] font-medium text-ds-userbubbleFg disabled:opacity-50"
              >
                {t('addBtn')}
              </button>
            </div>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => {
            cancelEndpointEdit()
            setShowAdd(true)
          }}
          className="mt-2 inline-flex items-center gap-1.5 rounded-xl border border-dashed border-ds-border px-3 py-2 text-[13px] font-medium text-ds-muted transition hover:border-accent/40 hover:bg-ds-hover hover:text-ds-ink"
        >
          <Plus className="h-4 w-4" strokeWidth={2} />
          {t('addEndpointBtn')}
        </button>
      )}
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
        checked ? 'bg-emerald-500' : 'bg-ds-faint'
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

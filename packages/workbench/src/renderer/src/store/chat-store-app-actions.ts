import type i18next from 'i18next'
import type { AppSettingsV1 } from '@shared/app-settings'
import { encodeModelRef } from '@shared/model-ref'
import { WORKBENCH_FEATURES } from '@shared/workbench-features'
import type { ComposerModelMeta } from '../lib/composer-model-label'
import {
  syncGitCommitSelection as mergeGitCommitSelection,
  toggleGitCommitPath as toggleGitCommitPathSelection,
  workspaceKey
} from '../lib/git-commit-selection'
import { resolveActiveThreadWorkspace } from '../lib/workspace-path'
import type { ChatState, ChatStoreGet, ChatStoreSet, InitialSetupMode, LegacySettingsRouteSection, PluginHostRoute, SettingsRouteSection } from './chat-store-types'

type CreateAppActionsOptions = {
  set: ChatStoreSet
  get: ChatStoreGet
  i18n: typeof i18next
  persistComposerModel: (model: string) => void
  readStoredComposerModel: (allowedIds: readonly string[]) => string
  mergeComposerPickList: (upstreamOk: boolean, upstreamIds: string[]) => string[]
  getComposerModelLoadPromise: () => Promise<void> | null
  setComposerModelLoadPromise: (promise: Promise<void> | null) => void
  applyTheme: (theme: AppSettingsV1['theme']) => void
  applyUiFontScale: (scale: AppSettingsV1['uiFontScale']) => void
  applyUiFontFamily: (family: AppSettingsV1['uiFontFamily']) => void
  workspaceLabelFromPath: (workspaceRoot: string) => string
  normalizeWorkspaceRoot: (workspaceRoot?: string | null) => string
}

export function createAppActions(options: CreateAppActionsOptions): Pick<
  ChatState,
  | 'setError'
  | 'setComposerModel'
  | 'loadComposerModels'
  | 'setRoute'
  | 'openSettings'
  | 'openPlugins'
  | 'openInitialSetup'
  | 'closeInitialSetup'
  | 'selectInspectorItem'
  | 'syncGitCommitSelection'
  | 'toggleGitCommitPath'
  | 'setGitCommitSelectedPaths'
  | 'applyI18nFromSettings'
  | 'reloadUiSettings'
> {
  const {
    set,
    get,
    i18n,
    persistComposerModel,
    readStoredComposerModel,
    mergeComposerPickList,
    getComposerModelLoadPromise,
    setComposerModelLoadPromise,
    applyTheme,
    applyUiFontScale,
    applyUiFontFamily,
    workspaceLabelFromPath,
    normalizeWorkspaceRoot
  } = options

  return {
    setError: (message) => set({ error: message }),

    setComposerModel: (modelId) => {
      persistComposerModel(modelId)
      set({ composerModel: modelId })
    },

    loadComposerModels: async () => {
      const existing = getComposerModelLoadPromise()
      if (existing) {
        await existing.catch(() => {})
      }
      if (typeof window.dsGui === 'undefined') return
      const task = (async () => {
        const res = await window.dsGui.fetchUpstreamModels()
        const upstreamIds = res.ok ? [...res.modelIds] : []
        // Inject custom endpoint models so they appear in the composer picker.
        // Also collect {ref → endpoint name + model label} so the picker chip can
        // render ``青云/claude-opus-4-6`` instead of the raw routing id.
        const metaMap: Record<string, ComposerModelMeta> = {}
        try {
          const settings = await window.dsGui.getSettings()
          for (const ep of settings.customEndpoints ?? []) {
            if (!ep.enabled) continue
            for (const model of ep.models) {
              if (!model.enabled) continue
              const ref = encodeModelRef(ep.id, model.id)
              if (model.id && !upstreamIds.includes(ref)) upstreamIds.push(ref)
              metaMap[ref] = { endpointName: ep.name, label: model.label }
            }
          }
        } catch { /* custom models are a bonus, not critical */ }
        const pick = mergeComposerPickList(res.ok || upstreamIds.length > 0, upstreamIds)
        const allowed = new Set(pick)
        set((state) => {
          let model = state.composerModel
          if (model !== '' && !allowed.has(model)) {
            model = readStoredComposerModel(pick)
          }
          if (model !== '' && !allowed.has(model)) model = ''
          if (model !== state.composerModel) persistComposerModel(model)
          return { composerPickList: pick, composerModel: model, composerModelMeta: metaMap }
        })
      })().finally(() => {
        setComposerModelLoadPromise(null)
      })
      setComposerModelLoadPromise(task)
      return task
    },

    setRoute: (route) => set({ route }),

    openSettings: (section: SettingsRouteSection | LegacySettingsRouteSection = 'general') => {
      const normalized: SettingsRouteSection =
        section === 'agents'
          ? 'models'
          : section === 'runtime' || section === 'claw'
            ? 'general'
            : section
      set({
        route: 'settings',
        settingsSection: normalized
      })
    },

    openPlugins: (host?: PluginHostRoute) => {
      if (!WORKBENCH_FEATURES.pluginMarketplace) return
      set({
        route: 'plugins',
        pluginHostRoute: host ?? 'chat'
      })
    },

    openInitialSetup: (mode: InitialSetupMode = 'required') =>
      set({ initialSetupOpen: true, initialSetupMode: mode }),

    closeInitialSetup: () => set({ initialSetupOpen: false, initialSetupMode: 'required' }),

    selectInspectorItem: (id) => set({ inspectorSelectedId: id }),

    syncGitCommitSelection: (allPaths) => {
      const state = get()
      const root = resolveActiveThreadWorkspace(
        state.activeThreadId,
        state.threads,
        state.workspaceRoot
      )
      const next = mergeGitCommitSelection(
        state.gitCommitSelectionKey,
        state.gitCommitSelectedPaths,
        root,
        allPaths
      )
      set({ gitCommitSelectionKey: next.key, gitCommitSelectedPaths: next.paths })
    },

    toggleGitCommitPath: (path, allPaths) => {
      const state = get()
      const root = resolveActiveThreadWorkspace(
        state.activeThreadId,
        state.threads,
        state.workspaceRoot
      )
      const key = workspaceKey(root) || null
      set({
        gitCommitSelectionKey: key,
        gitCommitSelectedPaths: toggleGitCommitPathSelection(
          state.gitCommitSelectedPaths,
          path,
          allPaths
        )
      })
    },

    setGitCommitSelectedPaths: (paths) => {
      const state = get()
      const root = resolveActiveThreadWorkspace(
        state.activeThreadId,
        state.threads,
        state.workspaceRoot
      )
      const key = workspaceKey(root) || null
      set({ gitCommitSelectionKey: key, gitCommitSelectedPaths: paths })
    },

    applyI18nFromSettings: async (locale) => {
      await i18n.changeLanguage(locale)
    },

    reloadUiSettings: async () => {
      if (typeof window.dsGui === 'undefined') return
      const settings = await window.dsGui.getSettings()
      const workspaceRoot = normalizeWorkspaceRoot(settings.workspaceRoot)
      applyTheme(settings.theme)
      applyUiFontScale(settings.uiFontScale)
      applyUiFontFamily(settings.uiFontFamily)
      set({
        providerId: settings.agentProvider,
        workspaceRoot,
        workspaceLabel: workspaceLabelFromPath(workspaceRoot)
      })
      await get().applyI18nFromSettings(settings.locale)
      if (get().runtimeConnection === 'ready') {
        void get().refreshThreads()
      }
      void get().loadComposerModels()
    }
  }
}

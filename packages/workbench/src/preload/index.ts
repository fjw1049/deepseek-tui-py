import { contextBridge, ipcRenderer } from 'electron'
import type { DsGuiApi } from '../shared/ds-gui-api'

const api = {
  platform: process.platform,
  getSettings: () => ipcRenderer.invoke('settings:get'),
  getStartupPhase: () => ipcRenderer.invoke('startup:phase:get'),
  onStartupPhase: (handler) => {
    const wrapped = (
      _: Electron.IpcRendererEvent,
      payload: Parameters<typeof handler>[0]
    ) => handler(payload)
    ipcRenderer.on('startup:phase', wrapped)
    return () => ipcRenderer.removeListener('startup:phase', wrapped)
  },
  setSettings: (partial) =>
    ipcRenderer.invoke('settings:set', partial),
  runtimeRequest: (path, method, body) =>
    ipcRenderer.invoke('runtime:request', { path, method, body }),
  fetchUpstreamModels: () => ipcRenderer.invoke('upstream:models'),
  deepseekSpawnIfNeeded: () =>
    ipcRenderer.invoke('deepseek:spawn-if-needed'),
  prepareDeepseekBinary: () => ipcRenderer.invoke('deepseek:prepare-binary'),
  pickWorkspaceDirectory: (defaultPath) =>
    ipcRenderer.invoke('workspace:pick-directory', defaultPath),
  pickWorkspaceFiles: (options) => ipcRenderer.invoke('workspace:pick-files', options),
  listTuiSessions: () => ipcRenderer.invoke('tui-sessions:list'),
  pickTuiSessionFile: (defaultPath) =>
    ipcRenderer.invoke('tui-sessions:pick-file', defaultPath),
  saveSkillFile: (rootPath, skillName, content) =>
    ipcRenderer.invoke('skill:save-file', { rootPath, skillName, content }),
  openSkillRoot: (rootPath) =>
    ipcRenderer.invoke('skill:open-root', rootPath),
  listSkillsInRoot: (rootPath) => ipcRenderer.invoke('skill:list-in-root', rootPath),
  getDeepseekConfigFile: () =>
    ipcRenderer.invoke('deepseek:config:read'),
  setDeepseekConfigFile: (content) =>
    ipcRenderer.invoke('deepseek:config:write', content),
  openDeepseekConfigDir: () =>
    ipcRenderer.invoke('deepseek:config:open-dir'),
  getMcpConfigFile: () => ipcRenderer.invoke('deepseek:mcp:read'),
  setMcpConfigFile: (content) => ipcRenderer.invoke('deepseek:mcp:write', content),
  openMcpConfigDir: () => ipcRenderer.invoke('deepseek:mcp:open-dir'),
  getFeishuConfig: () => ipcRenderer.invoke('feishu:config:read'),
  setFeishuConfig: (config) => ipcRenderer.invoke('feishu:config:write', config),
  openFeishuConfigDir: () => ipcRenderer.invoke('feishu:config:open-dir'),
  getWecomConfig: () => ipcRenderer.invoke('wecom:config:read'),
  setWecomConfig: (config) => ipcRenderer.invoke('wecom:config:write', config),
  startFeishuRegister: (options) => ipcRenderer.invoke('feishu:register-start', options ?? {}),
  cancelFeishuRegister: () => ipcRenderer.invoke('feishu:register-cancel'),
  onFeishuRegisterEvent: (handler) => {
    const wrapped = (_: Electron.IpcRendererEvent, payload: Parameters<typeof handler>[0]) =>
      handler(payload)
    ipcRenderer.on('feishu:register-event', wrapped)
    return () => ipcRenderer.removeListener('feishu:register-event', wrapped)
  },
  getEmailSecretStatus: () => ipcRenderer.invoke('email:secret:status'),
  setEmailSecret: (password) => ipcRenderer.invoke('email:secret:set', { password }),
  clearEmailSecret: () => ipcRenderer.invoke('email:secret:clear'),
  getDeepseekPaths: () => ipcRenderer.invoke('deepseek:paths:get'),
  openHooksDir: () => ipcRenderer.invoke('deepseek:hooks:open-dir'),
  testEndpoint: (protocol, baseUrl, apiKey, model) =>
    ipcRenderer.invoke('endpoint:test', { protocol, baseUrl, apiKey, model }),
  diagnoseDeepseekRuntime: () =>
    ipcRenderer.invoke('deepseek:diagnostics'),
  getWorkspaceSuggestions: (workspaceRoot) =>
    ipcRenderer.invoke('workspace:suggestions', workspaceRoot),
  getTrendingRepos: (period) => ipcRenderer.invoke('trending:repos', period),
  queryUsage: (params) => ipcRenderer.invoke('usage:query', params ?? {}),
  pruneUsageProvider: (providerId) => ipcRenderer.invoke('usage:prune-provider', { providerId }),
  pruneUsageEndpointModel: (providerId, modelId) =>
    ipcRenderer.invoke('usage:prune-endpoint-model', { providerId, modelId }),
  getGitBranches: (workspaceRoot) =>
    ipcRenderer.invoke('git:branches', workspaceRoot),
  getGitLog: (workspaceRoot) => ipcRenderer.invoke('git:log', workspaceRoot),
  getGitWorkingChanges: (workspaceRoot) =>
    ipcRenderer.invoke('git:working-changes', workspaceRoot),
  switchGitBranch: (workspaceRoot, branch) =>
    ipcRenderer.invoke('git:switch-branch', { workspaceRoot, branch }),
  createAndSwitchGitBranch: (workspaceRoot, branch) =>
    ipcRenderer.invoke('git:create-and-switch-branch', { workspaceRoot, branch }),
  commitGitChanges: (workspaceRoot, message, paths) =>
    ipcRenderer.invoke('git:commit', { workspaceRoot, message, paths }),
  suggestGitCommitMessage: (workspaceRoot, paths) =>
    ipcRenderer.invoke('git:suggest-commit-message', { workspaceRoot, paths }),
  listEditors: () => ipcRenderer.invoke('editor:list'),
  openEditorPath: (options) =>
    ipcRenderer.invoke('editor:open-path', options),
  createTerminalSession: (options) =>
    ipcRenderer.invoke('terminal:create', options),
  writeTerminalSession: (payload) =>
    ipcRenderer.invoke('terminal:write', payload),
  resizeTerminalSession: (payload) =>
    ipcRenderer.invoke('terminal:resize', payload),
  closeTerminalSession: (payload) =>
    ipcRenderer.invoke('terminal:close', payload),
  onTerminalData: (handler) => {
    const wrapped = (
      _: Electron.IpcRendererEvent,
      payload: Parameters<typeof handler>[0]
    ) => handler(payload)
    ipcRenderer.on('terminal:data', wrapped)
    return () => ipcRenderer.removeListener('terminal:data', wrapped)
  },
  onTerminalExit: (handler) => {
    const wrapped = (
      _: Electron.IpcRendererEvent,
      payload: Parameters<typeof handler>[0]
    ) => handler(payload)
    ipcRenderer.on('terminal:exit', wrapped)
    return () => ipcRenderer.removeListener('terminal:exit', wrapped)
  },
  resolveWorkspaceFile: (options) =>
    ipcRenderer.invoke('file:resolve-workspace', options),
  readWorkspaceFile: (options) =>
    ipcRenderer.invoke('file:read-workspace', options),
  startSse: (threadId, sinceSeq, streamId) =>
    ipcRenderer.invoke('runtime:sse:start', { threadId, sinceSeq, streamId }),
  stopSse: (streamId) => ipcRenderer.invoke('runtime:sse:stop', streamId),
  regenerateRuntimeToken: () => ipcRenderer.invoke('runtime:regenerate-token'),
  getRuntimeTokenFingerprint: () => ipcRenderer.invoke('runtime:get-token-fingerprint'),
  onSseEvent: (handler) => {
    const wrapped = (
      _: Electron.IpcRendererEvent,
      payload: Parameters<typeof handler>[0]
    ) => handler(payload)
    ipcRenderer.on('runtime:sse-event', wrapped)
    return () => ipcRenderer.removeListener('runtime:sse-event', wrapped)
  },
  onSseEnd: (handler) => {
    const wrapped = (
      _: Electron.IpcRendererEvent,
      payload: Parameters<typeof handler>[0]
    ) => handler(payload)
    ipcRenderer.on('runtime:sse-end', wrapped)
    return () => ipcRenderer.removeListener('runtime:sse-end', wrapped)
  },
  onSseError: (handler) => {
    const wrapped = (
      _: Electron.IpcRendererEvent,
      payload: Parameters<typeof handler>[0]
    ) => handler(payload)
    ipcRenderer.on('runtime:sse-error', wrapped)
    return () => ipcRenderer.removeListener('runtime:sse-error', wrapped)
  },
  openExternal: (url) => ipcRenderer.invoke('shell:open-external', url),
  showTurnCompleteNotification: (payload) => ipcRenderer.invoke('notification:turn-complete', payload),
  getAppVersion: () => ipcRenderer.invoke('app:version'),
  logError: (category, message, detail) =>
    ipcRenderer.invoke('log:error', { category, message, detail }),
  getLogPath: () => ipcRenderer.invoke('log:get-path'),
  openLogDir: () => ipcRenderer.invoke('log:open-dir'),
  fetchPetManifest: (force) => ipcRenderer.invoke('pet:fetch-manifest', force === true),
  resolvePetSpritesheet: (slug) =>
    ipcRenderer.invoke('pet:resolve-spritesheet', slug ? { slug } : {}),
  cacheFeaturedPets: (limit) => ipcRenderer.invoke('pet:cache-featured', limit)
} satisfies DsGuiApi

contextBridge.exposeInMainWorld('dsGui', api)

import {
  getMcpServerEntry,
  listMcpServers,
  mergeMcpServerIntoConfig,
  patchMcpServerEntry,
  setMcpServerLoadPolicy,
  type McpLoadPolicy,
  type McpServerEntry
} from './mcp-json-merge'

/** Always-loaded (progressive) default connectors. */
export const DEFAULT_CONNECTOR_IDS = new Set(['bing-search', 'bing-cn-mcp-server'])

export const BING_SEARCH_SERVER_ID = 'bing-search'
export const YAHOO_FINANCE_SERVER_ID = 'yahoo-finance'

export const BING_SEARCH_ENTRY: McpServerEntry = {
  command: 'npx',
  args: ['-y', 'bing-cn-mcp'],
  enabled: true,
  disabled: false,
  required: false,
  load_policy: 'progressive'
}

export const YAHOO_FINANCE_ENTRY: McpServerEntry = {
  command: 'uvx',
  args: ['--python', '3.13', '--with', 'mcp==1.6.0', 'mcp-yahoo-finance'],
  enabled: true,
  disabled: false,
  required: false,
  load_policy: 'on_focus'
}

export type ConnectorGroup = 'default' | 'activated'

export function isDefaultConnector(id: string): boolean {
  return DEFAULT_CONNECTOR_IDS.has(id)
}

export function classifyConnector(id: string, loadPolicy?: McpLoadPolicy): ConnectorGroup {
  if (isDefaultConnector(id)) return 'default'
  if (id === YAHOO_FINANCE_SERVER_ID) return 'activated'
  return loadPolicy === 'progressive' ? 'default' : 'activated'
}

export function presetConnectorTitle(id: string): string | null {
  if (isDefaultConnector(id)) return 'Bing Search'
  if (id === YAHOO_FINANCE_SERVER_ID) return 'Yahoo Finance'
  return null
}

/**
 * Marketplace / manual installs default to on_focus (plug-and-play).
 * Callers that already set ``load_policy`` are left untouched.
 */
export function withDefaultOnFocusPolicy(entry: McpServerEntry): McpServerEntry {
  if (entry.load_policy === 'progressive' || entry.load_policy === 'on_focus') {
    return entry
  }
  return { ...entry, load_policy: 'on_focus' satisfies McpLoadPolicy }
}

export function withInstallLoadPolicy(id: string, entry: McpServerEntry): McpServerEntry {
  if (isDefaultConnector(id)) {
    return { ...entry, load_policy: 'progressive' }
  }
  return withDefaultOnFocusPolicy(entry)
}

export function partitionConnectorsByGroup<T extends { id: string; loadPolicy?: McpLoadPolicy }>(
  items: T[]
): { default: T[]; activated: T[] } {
  const defaultItems: T[] = []
  const activated: T[] = []
  for (const item of items) {
    if (classifyConnector(item.id, item.loadPolicy) === 'default') defaultItems.push(item)
    else activated.push(item)
  }
  return { default: defaultItems, activated }
}

/**
 * Ensure Bing Search is the always-loaded default, and Yahoo Finance is
 * the plug-and-play activated preset. Existing command/env are left intact;
 * only missing servers and known-id load policies are written.
 */
export function ensurePresetConnectors(raw: string): { next: string; changed: boolean } {
  let next = raw
  let changed = false
  const existing = listMcpServers(raw)
  const hasDefault = existing.some((server) => isDefaultConnector(server.id))

  if (existing.length === 0) {
    next = mergeMcpServerIntoConfig(next, BING_SEARCH_SERVER_ID, BING_SEARCH_ENTRY)
    next = mergeMcpServerIntoConfig(next, YAHOO_FINANCE_SERVER_ID, YAHOO_FINANCE_ENTRY)
    return { next, changed: true }
  }

  if (!hasDefault) {
    next = mergeMcpServerIntoConfig(next, BING_SEARCH_SERVER_ID, BING_SEARCH_ENTRY)
    changed = true
  }

  for (const server of listMcpServers(next)) {
    const desired = desiredPresetLoadPolicy(server.id)
    if (desired && server.loadPolicy !== desired) {
      next = setMcpServerLoadPolicy(next, server.id, desired)
      changed = true
    }
    if (isDefaultConnector(server.id) && needsBingCommandFix(getMcpServerEntry(next, server.id))) {
      next = patchMcpServerEntry(next, server.id, {
        command: BING_SEARCH_ENTRY.command,
        args: BING_SEARCH_ENTRY.args
      })
      changed = true
    }
  }

  return { next, changed }
}

function needsBingCommandFix(entry: McpServerEntry): boolean {
  const args = entry.args ?? []
  return (entry.command ?? 'npx') === 'npx' && args.includes('bing-cn-mcp') && !args.includes('-y')
}

function desiredPresetLoadPolicy(id: string): McpLoadPolicy | null {
  if (isDefaultConnector(id)) return 'progressive'
  if (id === YAHOO_FINANCE_SERVER_ID) return 'on_focus'
  return null
}

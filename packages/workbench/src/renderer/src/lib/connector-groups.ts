import type { McpLoadPolicy, McpServerEntry } from './mcp-json-merge'

/** Progressive preload allowlist — only these appear under「自带」. */
export const BUILTIN_CONNECTOR_IDS = new Set(['yahoo-finance'])

export type ConnectorGroup = 'builtin' | 'activated'

export function classifyConnector(id: string): ConnectorGroup {
  return BUILTIN_CONNECTOR_IDS.has(id) ? 'builtin' : 'activated'
}

export function isBuiltinConnector(id: string): boolean {
  return classifyConnector(id) === 'builtin'
}

/**
 * Non-builtin installs default to on_focus so progressive tool search
 * does not pull every marketplace/manual connector into the model context.
 * Callers that already set ``load_policy`` are left untouched.
 */
export function withDefaultOnFocusPolicy(entry: McpServerEntry): McpServerEntry {
  if (entry.load_policy === 'progressive' || entry.load_policy === 'on_focus') {
    return entry
  }
  return { ...entry, load_policy: 'on_focus' satisfies McpLoadPolicy }
}

export function partitionConnectorsByGroup<T extends { id: string }>(
  items: T[]
): { builtin: T[]; activated: T[] } {
  const builtin: T[] = []
  const activated: T[] = []
  for (const item of items) {
    if (isBuiltinConnector(item.id)) builtin.push(item)
    else activated.push(item)
  }
  return { builtin, activated }
}

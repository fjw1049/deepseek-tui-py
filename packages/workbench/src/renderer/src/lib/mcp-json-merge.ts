export type McpLoadPolicy = 'progressive' | 'on_focus'

export type McpServerEntry = {
  command?: string
  args?: string[]
  url?: string
  env?: Record<string, string>
  /** Extra HTTP headers for url / streamablehttp transports (e.g. Authorization). */
  headers?: Record<string, string>
  /**
   * Cursor-style transport hint: ``streamablehttp`` / ``sse`` / ``stdio``.
   * Ignored for stdio (command) servers.
   */
  type?: string
  timeout?: number
  enabled?: boolean
  disabled?: boolean
  required?: boolean
  /** progressive (default) — catalog + tool_search; on_focus — @connector only */
  load_policy?: McpLoadPolicy
  /** Catalog bucket, e.g. media / sports */
  catalog?: string
}

const MCP_DOC_META_KEYS = new Set(['timeouts', 'mcp', 'mcpServers', 'servers'])

/** True when ``value`` looks like a single MCP server config object. */
export function looksLikeMcpServerEntry(value: unknown): boolean {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const entry = value as Record<string, unknown>
  return typeof entry.command === 'string' || typeof entry.url === 'string'
}

/**
 * Pull the servers table from a parsed document.
 * Accepts ``mcp.servers``, ``servers``, ``mcpServers``, or a bare
 * Cursor-style map ``{ "name": { url|command, ... } }``.
 */
export function extractMcpServersFromDocument(
  doc: Record<string, unknown>
): Record<string, McpServerEntry> {
  const mcp = doc.mcp
  if (mcp && typeof mcp === 'object' && !Array.isArray(mcp)) {
    const nested = (mcp as Record<string, unknown>).servers
    if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
      return nested as Record<string, McpServerEntry>
    }
  }
  if (doc.mcpServers && typeof doc.mcpServers === 'object' && !Array.isArray(doc.mcpServers)) {
    return doc.mcpServers as Record<string, McpServerEntry>
  }
  if (doc.servers && typeof doc.servers === 'object' && !Array.isArray(doc.servers)) {
    return doc.servers as Record<string, McpServerEntry>
  }
  // Bare server table (Cursor snippet without mcpServers wrapper).
  if (!('mcpServers' in doc) && !('servers' in doc) && !('mcp' in doc)) {
    const entries = Object.entries(doc).filter(([key]) => !MCP_DOC_META_KEYS.has(key))
    if (entries.length > 0 && entries.every(([, value]) => looksLikeMcpServerEntry(value))) {
      return Object.fromEntries(entries) as Record<string, McpServerEntry>
    }
  }
  return {}
}

/**
 * Resolve the servers map from supported mcp.json shapes.
 * Prefer nested ``mcp.servers`` (TikHub form), then ``servers``, then ``mcpServers``.
 */
function serversTable(doc: Record<string, unknown>): Record<string, unknown> {
  const mcp = doc.mcp
  if (mcp && typeof mcp === 'object' && !Array.isArray(mcp)) {
    const nested = (mcp as Record<string, unknown>).servers
    if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
      return nested as Record<string, unknown>
    }
    const next: Record<string, unknown> = {}
    ;(mcp as Record<string, unknown>).servers = next
    return next
  }
  const servers = doc.servers ?? doc.mcpServers
  if (servers && typeof servers === 'object' && !Array.isArray(servers)) {
    return servers as Record<string, unknown>
  }
  // Default new documents to nested TikHub-compatible shape.
  const next: Record<string, unknown> = {}
  doc.mcp = { servers: next }
  return next
}

export function parseMcpConfigDocument(raw: string): Record<string, unknown> {
  const trimmed = raw.trim()
  if (!trimmed) {
    return { mcp: { servers: {} } }
  }
  const parsed = JSON.parse(trimmed) as unknown
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('MCP config must be a JSON object.')
  }
  return parsed as Record<string, unknown>
}

export function mcpConfigHasServer(raw: string, serverId: string): boolean {
  try {
    const doc = parseMcpConfigDocument(raw)
    const servers = serversTable(doc)
    return Object.prototype.hasOwnProperty.call(servers, serverId)
  } catch {
    return raw.includes(`"${serverId}"`)
  }
}

export function mergeMcpServerIntoConfig(
  raw: string,
  serverId: string,
  entry: McpServerEntry
): string {
  const doc = parseMcpConfigDocument(raw)
  const servers = serversTable(doc)
  // Media / TikHub-style entries already carry command+args; don't force
  // enabled/disabled/required unless the caller omitted them and the server
  // is not a media on_focus connector (those stay minimal like TikHub docs).
  const isMediaFocus =
    entry.load_policy === 'on_focus' || entry.catalog === 'media'
  servers[serverId] = isMediaFocus
    ? { ...entry }
    : {
        enabled: true,
        disabled: false,
        required: false,
        ...entry
      }
  return `${JSON.stringify(doc, null, 2)}\n`
}

export function removeMcpServerFromConfig(raw: string, serverId: string): string {
  const doc = parseMcpConfigDocument(raw)
  const servers = serversTable(doc)
  if (!Object.prototype.hasOwnProperty.call(servers, serverId)) {
    throw new Error(`MCP server "${serverId}" not found.`)
  }
  delete servers[serverId]
  return `${JSON.stringify(doc, null, 2)}\n`
}

export function buildMcpServerEntry(
  command: string,
  args: string[],
  env?: Record<string, string>,
  timeout?: number
): McpServerEntry {
  const entry: McpServerEntry = {
    command,
    args,
    enabled: true,
    disabled: false,
    required: false
  }
  if (env && Object.keys(env).length > 0) {
    entry.env = env
  }
  if (typeof timeout === 'number' && Number.isFinite(timeout) && timeout > 0) {
    entry.timeout = timeout
  }
  return entry
}

/**
 * Split a pasted command line into a command + args, honoring single/double
 * quotes so paths with spaces survive. Not a full shell parser — no escapes or
 * variable expansion — but enough for the common `npx -y pkg "/some path"` case.
 */
export function tokenizeCommandLine(input: string): { command: string; args: string[] } {
  const tokens: string[] = []
  let current = ''
  let quote: '"' | "'" | null = null
  let hasCurrent = false
  for (const char of input.trim()) {
    if (quote) {
      if (char === quote) quote = null
      else current += char
      continue
    }
    if (char === '"' || char === "'") {
      quote = char
      hasCurrent = true
      continue
    }
    if (/\s/.test(char)) {
      if (hasCurrent) {
        tokens.push(current)
        current = ''
        hasCurrent = false
      }
      continue
    }
    current += char
    hasCurrent = true
  }
  if (hasCurrent) tokens.push(current)
  const [command = '', ...args] = tokens
  return { command, args }
}

/** Build an SSE (URL-based) MCP server entry. Mirrors {@link buildMcpServerEntry}. */
export function buildSseServerEntry(
  url: string,
  env?: Record<string, string>,
  timeout?: number
): McpServerEntry {
  const entry: McpServerEntry = {
    url,
    enabled: true,
    disabled: false,
    required: false
  }
  if (env && Object.keys(env).length > 0) {
    entry.env = env
  }
  if (typeof timeout === 'number' && Number.isFinite(timeout) && timeout > 0) {
    entry.timeout = timeout
  }
  return entry
}

export type McpServerSummary = {
  id: string
  enabled: boolean
  summary: string
  loadPolicy: McpLoadPolicy
  catalog?: string
}

export function normalizeMcpLoadPolicy(value: unknown): McpLoadPolicy {
  return value === 'on_focus' ? 'on_focus' : 'progressive'
}

function asMcpServerEntry(value: unknown): McpServerEntry {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return {}
  }
  return value as McpServerEntry
}

export function isMcpServerEnabled(entry: McpServerEntry): boolean {
  if (entry.disabled === true) return false
  if (entry.enabled === false) return false
  return true
}

function summarizeMcpServer(entry: McpServerEntry): string {
  if (entry.url?.trim()) return entry.url.trim()
  const command = entry.command?.trim() || ''
  const args = (entry.args ?? []).join(' ').trim()
  const line = [command, args].filter(Boolean).join(' ')
  return line || '—'
}

export function listMcpServers(raw: string): McpServerSummary[] {
  const doc = parseMcpConfigDocument(raw)
  const servers = serversTable(doc)
  return Object.entries(servers)
    .map(([id, value]) => {
      const entry = asMcpServerEntry(value)
      const catalog = entry.catalog?.trim()
      return {
        id,
        enabled: isMcpServerEnabled(entry),
        summary: summarizeMcpServer(entry),
        loadPolicy: normalizeMcpLoadPolicy(entry.load_policy),
        ...(catalog ? { catalog } : {})
      }
    })
    .sort((a, b) => a.id.localeCompare(b.id))
}

/** Read a single server entry (empty object if missing). */
export function getMcpServerEntry(raw: string, serverId: string): McpServerEntry {
  try {
    const doc = parseMcpConfigDocument(raw)
    const servers = serversTable(doc)
    return asMcpServerEntry(servers[serverId])
  } catch {
    return {}
  }
}

export function setMcpServerEnabled(raw: string, serverId: string, enabled: boolean): string {
  const doc = parseMcpConfigDocument(raw)
  const servers = serversTable(doc)
  const current = asMcpServerEntry(servers[serverId])
  if (!servers[serverId]) {
    throw new Error(`MCP server "${serverId}" not found.`)
  }
  servers[serverId] = {
    ...current,
    enabled,
    disabled: !enabled
  }
  return `${JSON.stringify(doc, null, 2)}\n`
}

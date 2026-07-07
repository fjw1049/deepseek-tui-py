export type McpServerEntry = {
  command?: string
  args?: string[]
  url?: string
  env?: Record<string, string>
  enabled?: boolean
  disabled?: boolean
  required?: boolean
}

function serversTable(doc: Record<string, unknown>): Record<string, unknown> {
  const servers = doc.mcpServers ?? doc.servers
  if (servers && typeof servers === 'object' && !Array.isArray(servers)) {
    return servers as Record<string, unknown>
  }
  const next: Record<string, unknown> = {}
  doc.mcpServers = next
  return next
}

export function parseMcpConfigDocument(raw: string): Record<string, unknown> {
  const trimmed = raw.trim()
  if (!trimmed) {
    return { mcpServers: {} }
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
  servers[serverId] = {
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
  env?: Record<string, string>
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
  return entry
}

export type McpServerSummary = {
  id: string
  enabled: boolean
  summary: string
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
      return {
        id,
        enabled: isMcpServerEnabled(entry),
        summary: summarizeMcpServer(entry)
      }
    })
    .sort((a, b) => a.id.localeCompare(b.id))
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

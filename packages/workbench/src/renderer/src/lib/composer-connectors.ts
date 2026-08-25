import { MEDIA_CATALOG } from '../components/extensions/media-catalog'
import { classifyConnector, presetConnectorTitle, type ConnectorGroup } from './connector-groups'
import {
  listMcpServers,
  normalizeMcpLoadPolicy,
  type McpServerSummary
} from './mcp-json-merge'

export type ComposerConnectorSection = ConnectorGroup

export type ConnectorRuntimeStatus = 'connected' | 'connecting' | 'failed' | 'disabled'

export type ComposerConnectorRow = {
  id: string
  /** Human title for UI (e.g. 微信公众号); falls back to id. */
  title: string
  summary: string
  connected: boolean
  status: ConnectorRuntimeStatus
  error?: string | null
  enabled: boolean
  loadPolicy: 'progressive' | 'on_focus'
  section: ComposerConnectorSection
  /** Reserved; composer no longer lists unconfigured media stubs. */
  needsConfig: boolean
}

type RuntimeServer = {
  name: string
  transport?: string
  connected?: boolean
  status?: string
  error?: string | null
  enabled?: boolean
  load_policy?: string
  catalog?: string | null
}

export function resolveConnectorRuntimeStatus(
  runtime?: Pick<RuntimeServer, 'connected' | 'status' | 'enabled'>
): ConnectorRuntimeStatus {
  if (runtime?.enabled === false) return 'disabled'
  const raw = runtime?.status
  if (raw === 'connected' || raw === 'connecting' || raw === 'failed' || raw === 'disabled') {
    return raw
  }
  if (runtime?.connected === true) return 'connected'
  // Missing / stale runtime: still warming, never treat as failed.
  return 'connecting'
}

export function isComposerConnectorSelectable(
  row: Pick<ComposerConnectorRow, 'enabled' | 'status'>
): boolean {
  return row.enabled && row.status === 'connected'
}

export function composerConnectorDotTone(
  row: Pick<ComposerConnectorRow, 'status'>
): 'green' | 'yellow' | 'red' {
  if (row.status === 'connected') return 'green'
  if (row.status === 'connecting') return 'yellow'
  return 'red'
}

export function composerConnectorDotClass(tone: 'green' | 'yellow' | 'red'): string {
  if (tone === 'green') return 'bg-emerald-500'
  if (tone === 'yellow') return 'bg-amber-400 animate-pulse'
  return 'bg-red-500'
}

export function parseMcpRuntimeServers(body: string): RuntimeServer[] {
  try {
    const parsed = JSON.parse(body) as { servers?: RuntimeServer[] }
    return Array.isArray(parsed.servers) ? parsed.servers : []
  } catch {
    return []
  }
}

export type BuildComposerConnectorRowsInput = {
  /** Live runtime `/v1/mcp/servers` (connection dots). */
  runtimeServers?: RuntimeServer[]
  /** Disk `mcp.json` — source of truth for 默认 / 激活. */
  diskServers?: McpServerSummary[]
}

const MEDIA_BY_ID = new Map(MEDIA_CATALOG.map((item) => [item.id, item]))

export function mediaConnectorTitle(id: string): string | null {
  return MEDIA_BY_ID.get(id)?.title ?? null
}

/**
 * Build 默认 / 激活 rows from mcp.json (+ runtime connection dots).
 * Unconfigured media catalog stubs are not listed — configure under Connectors → Media.
 */
export function buildComposerConnectorRows(
  input: BuildComposerConnectorRowsInput | RuntimeServer[] = {}
): ComposerConnectorRow[] {
  // Back-compat: older call sites passed a bare runtime server array.
  const normalized: BuildComposerConnectorRowsInput = Array.isArray(input)
    ? { runtimeServers: input }
    : input
  const runtimeServers = normalized.runtimeServers ?? []
  const diskServers = normalized.diskServers ?? []

  const runtimeByName = new Map(runtimeServers.map((s) => [s.name, s]))
  const byId = new Map<string, ComposerConnectorRow>()

  for (const disk of diskServers) {
    if (!disk.enabled) continue
    const runtime = runtimeByName.get(disk.id)
    const loadPolicy = normalizeMcpLoadPolicy(disk.loadPolicy)
    const media = MEDIA_BY_ID.get(disk.id)
    const section = classifyConnector(disk.id, loadPolicy)
    const status = resolveConnectorRuntimeStatus(runtime)

    byId.set(disk.id, {
      id: disk.id,
      title: media?.title ?? presetConnectorTitle(disk.id) ?? disk.id,
      summary: media?.description ?? disk.summary,
      connected: status === 'connected',
      status,
      error: runtime?.error ?? null,
      enabled: true,
      loadPolicy,
      section,
      needsConfig: false
    })
  }

  // Runtime-only servers not yet mirrored in disk parse (rare) → keep visible
  for (const s of runtimeServers) {
    if (!s.name || byId.has(s.name)) continue
    if (s.enabled === false) continue
    const media = MEDIA_BY_ID.get(s.name)
    const loadPolicy = s.load_policy === 'on_focus' ? 'on_focus' : 'progressive'
    const status = resolveConnectorRuntimeStatus(s)
    byId.set(s.name, {
      id: s.name,
      title: media?.title ?? presetConnectorTitle(s.name) ?? s.name,
      summary: media?.description ?? s.transport ?? '',
      connected: status === 'connected',
      status,
      error: s.error ?? null,
      enabled: true,
      loadPolicy,
      section: classifyConnector(s.name, loadPolicy),
      needsConfig: false
    })
  }

  return [...byId.values()].sort((a, b) => {
    if (a.section !== b.section) return a.section === 'default' ? -1 : 1
    return a.title.localeCompare(b.title, 'zh')
  })
}

export function diskServersFromMcpConfig(raw: string): McpServerSummary[] {
  try {
    return listMcpServers(raw)
  } catch {
    return []
  }
}

export function filterComposerConnectorRows(
  rows: ComposerConnectorRow[],
  query: string
): ComposerConnectorRow[] {
  const q = query.trim().toLowerCase()
  if (!q) return rows
  return rows.filter(
    (c) =>
      c.id.toLowerCase().includes(q) ||
      c.title.toLowerCase().includes(q) ||
      c.summary.toLowerCase().includes(q)
  )
}

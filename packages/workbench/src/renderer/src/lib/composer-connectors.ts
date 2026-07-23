import { MEDIA_CATALOG } from '../components/extensions/media-catalog'
import { classifyConnector, type ConnectorGroup } from './connector-groups'
import {
  listMcpServers,
  normalizeMcpLoadPolicy,
  type McpServerSummary
} from './mcp-json-merge'

export type ComposerConnectorSection = ConnectorGroup

export type ComposerConnectorRow = {
  id: string
  /** Human title for UI (e.g. 微信公众号); falls back to id. */
  title: string
  summary: string
  connected: boolean
  enabled: boolean
  loadPolicy: 'progressive' | 'on_focus'
  section: ComposerConnectorSection
  /** Reserved; composer no longer lists unconfigured media stubs. */
  needsConfig: boolean
  brand?: string
}

type RuntimeServer = {
  name: string
  transport?: string
  connected?: boolean
  enabled?: boolean
  load_policy?: string
  catalog?: string | null
}

export type BuildComposerConnectorRowsInput = {
  /** Live runtime `/v1/mcp/servers` (connection dots). */
  runtimeServers?: RuntimeServer[]
  /** Disk `mcp.json` — source of truth for 自带 / 已激活. */
  diskServers?: McpServerSummary[]
}

const MEDIA_BY_ID = new Map(MEDIA_CATALOG.map((item) => [item.id, item]))

export function mediaConnectorTitle(id: string): string | null {
  return MEDIA_BY_ID.get(id)?.title ?? null
}

/**
 * Build 自带 / 已激活 rows from mcp.json (+ runtime connection dots).
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
    const section = classifyConnector(disk.id)

    byId.set(disk.id, {
      id: disk.id,
      title: media?.title ?? disk.id,
      summary: media?.description ?? disk.summary,
      connected: runtime?.connected === true,
      enabled: true,
      loadPolicy,
      section,
      needsConfig: false,
      brand: media?.brand
    })
  }

  // Runtime-only servers not yet mirrored in disk parse (rare) → keep visible
  for (const s of runtimeServers) {
    if (!s.name || byId.has(s.name)) continue
    if (s.enabled === false) continue
    const media = MEDIA_BY_ID.get(s.name)
    const loadPolicy = s.load_policy === 'on_focus' ? 'on_focus' : 'progressive'
    byId.set(s.name, {
      id: s.name,
      title: media?.title ?? s.name,
      summary: media?.description ?? s.transport ?? '',
      connected: s.connected === true,
      enabled: true,
      loadPolicy,
      section: classifyConnector(s.name),
      needsConfig: false,
      brand: media?.brand
    })
  }

  return [...byId.values()].sort((a, b) => {
    if (a.section !== b.section) return a.section === 'builtin' ? -1 : 1
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
  section: ComposerConnectorSection,
  query: string
): ComposerConnectorRow[] {
  const q = query.trim().toLowerCase()
  return rows.filter((c) => {
    if (c.section !== section) return false
    if (!q) return true
    return (
      c.id.toLowerCase().includes(q) ||
      c.title.toLowerCase().includes(q) ||
      c.summary.toLowerCase().includes(q)
    )
  })
}

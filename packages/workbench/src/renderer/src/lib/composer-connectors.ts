import { MEDIA_CATALOG } from '../components/extensions/media-catalog'
import {
  listMcpServers,
  normalizeMcpLoadPolicy,
  type McpServerSummary
} from './mcp-json-merge'

export type ComposerConnectorSection = 'installed' | 'media'

export type ComposerConnectorRow = {
  id: string
  /** Human title for UI (e.g. 微信公众号); falls back to id. */
  title: string
  summary: string
  connected: boolean
  enabled: boolean
  loadPolicy: 'progressive' | 'on_focus'
  section: ComposerConnectorSection
  /** True when listed from media catalog but not yet in mcp.json / disabled. */
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
  /** Disk `mcp.json` — source of truth for 已安装 (same as Connectors settings). */
  diskServers?: McpServerSummary[]
}

const MEDIA_BY_ID = new Map(MEDIA_CATALOG.map((item) => [item.id, item]))

export function mediaConnectorTitle(id: string): string | null {
  return MEDIA_BY_ID.get(id)?.title ?? null
}

function isMediaId(id: string, catalog?: string | null, loadPolicy?: string): boolean {
  if (MEDIA_BY_ID.has(id)) return true
  if (catalog === 'media') return true
  // on_focus without media catalog still goes to 媒体 if id is tikhub-*
  if (loadPolicy === 'on_focus' && id.startsWith('tikhub-')) return true
  return false
}

/**
 * Build 已安装 / 媒体 rows.
 * 已安装 comes from mcp.json (yahoo etc.); runtime only supplies connected dots.
 * 媒体 is the TikHub catalog (+ configured media entries).
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

  // 1) Disk mcp.json → 已安装 + configured 媒体
  for (const disk of diskServers) {
    const runtime = runtimeByName.get(disk.id)
    const loadPolicy = normalizeMcpLoadPolicy(disk.loadPolicy)
    const catalog = disk.catalog ?? runtime?.catalog ?? null
    const media = MEDIA_BY_ID.get(disk.id)
    const section: ComposerConnectorSection = isMediaId(disk.id, catalog, loadPolicy)
      ? 'media'
      : 'installed'

    if (section === 'installed' && !disk.enabled) continue

    byId.set(disk.id, {
      id: disk.id,
      title: media?.title ?? disk.id,
      summary: media?.description ?? disk.summary,
      connected: runtime?.connected === true,
      enabled: disk.enabled,
      loadPolicy: section === 'media' ? 'on_focus' : loadPolicy,
      section,
      needsConfig: section === 'media' && !disk.enabled,
      brand: media?.brand
    })
  }

  // 2) Runtime-only servers not yet mirrored in disk parse (rare) → keep visible
  for (const s of runtimeServers) {
    if (!s.name || byId.has(s.name)) continue
    if (s.enabled === false) continue
    const media = MEDIA_BY_ID.get(s.name)
    const loadPolicy = s.load_policy === 'on_focus' ? 'on_focus' : 'progressive'
    const section: ComposerConnectorSection = isMediaId(s.name, s.catalog, loadPolicy)
      ? 'media'
      : 'installed'
    byId.set(s.name, {
      id: s.name,
      title: media?.title ?? s.name,
      summary: media?.description ?? s.transport ?? '',
      connected: s.connected === true,
      enabled: true,
      loadPolicy: section === 'media' ? 'on_focus' : loadPolicy,
      section,
      needsConfig: false,
      brand: media?.brand
    })
  }

  // 3) Full media catalog stubs
  for (const item of MEDIA_CATALOG) {
    if (byId.has(item.id)) continue
    byId.set(item.id, {
      id: item.id,
      title: item.title,
      summary: item.description,
      connected: false,
      enabled: false,
      loadPolicy: 'on_focus',
      section: 'media',
      needsConfig: true,
      brand: item.brand
    })
  }

  return [...byId.values()].sort((a, b) => {
    if (a.section !== b.section) return a.section === 'installed' ? -1 : 1
    if (a.needsConfig !== b.needsConfig) return a.needsConfig ? 1 : -1
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

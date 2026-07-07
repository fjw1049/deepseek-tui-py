import { app } from 'electron'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'

import type {
  MarketplaceCatalogResult,
  MarketplaceCategory,
  MarketplaceItem,
  MarketplaceKind,
  SkillMarkdownResult
} from '../../shared/ds-gui-api'

// Public ModelScope marketplaces. MUST use the `.ai` host — `.cn` sits behind an
// Aliyun WAF that answers the MCP endpoint with a JS challenge page instead of JSON.
const ENDPOINTS: Record<MarketplaceKind, { url: string; referer: string; body: string }> = {
  mcp: {
    url: 'https://www.modelscope.ai/api/v1/dolphin/mcpServers',
    referer: 'https://www.modelscope.ai/mcp',
    body: JSON.stringify({ PageSize: 30, PageNumber: 1, Query: '', Criterion: [] })
  },
  skill: {
    url: 'https://www.modelscope.ai/api/v1/dolphin/skills',
    referer: 'https://www.modelscope.ai/skills',
    // WithTopCollection:false returns the flat `SkillList` shape (vs the nested
    // SkillCollection when true) which is far cleaner to normalize.
    body: JSON.stringify({
      PageSize: 30,
      PageNumber: 1,
      Query: '',
      Sort: 'Default',
      Criterion: [],
      WithTopCollection: false
    })
  }
}

const CATALOG_TTL_MS = 24 * 60 * 60 * 1000
const FETCH_TIMEOUT_MS = 15_000
const README_MAX = 40_000
const USER_AGENT =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'

type CacheRecord = { fetchedAt: number; items: MarketplaceItem[]; categories: MarketplaceCategory[] }

const memoryCache = new Map<MarketplaceKind, CacheRecord>()

function cacheRoot(): string {
  return join(app.getPath('userData'), 'marketplace-cache')
}

function cachePath(kind: MarketplaceKind): string {
  return join(cacheRoot(), `${kind}.json`)
}

function asObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function num(value: unknown): number {
  return typeof value === 'number' ? value : 0
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

// ---- normalization -------------------------------------------------------

function normalizeMcp(data: Record<string, unknown>): { items: MarketplaceItem[]; categories: MarketplaceCategory[] } {
  const server = asObject(data.McpServer)
  const rows = Array.isArray(server?.McpServers) ? server.McpServers : []
  const items: MarketplaceItem[] = []
  for (const raw of rows) {
    const row = asObject(raw)
    if (!row) continue
    const id = str(row.Name).trim()
    if (!id) continue
    const readme = str(row.Readme)
    items.push({
      id,
      name: str(row.ChineseName).trim() || id,
      description: (str(row.AbstractCN) || str(row.Abstract)).trim(),
      publisher: str(row.Publisher).trim(),
      categories: stringList(row.Category),
      sourceUrl: str(row.FromSiteUrl).trim(),
      deployedUrl: str(row.DeployedUrl).trim(),
      deployedTransport: str(row.DeployedUrlTransportType).trim(),
      readme: readme.length > README_MAX ? readme.slice(0, README_MAX) : readme,
      metric: num(row.CallVolume),
      isTop: num(row.IsTop)
    })
  }
  const agg = asObject(data.FiledAgg)
  const catRows = Array.isArray(agg?.Category) ? agg.Category : []
  const categories: MarketplaceCategory[] = []
  for (const raw of catRows) {
    const row = asObject(raw)
    const value = str(row?.Value).trim()
    if (value) categories.push({ value, count: num(row?.Count) })
  }
  categories.sort((a, b) => b.count - a.count)
  return { items, categories: categories.slice(0, 12) }
}

function normalizeSkill(data: Record<string, unknown>): { items: MarketplaceItem[]; categories: MarketplaceCategory[] } {
  const rows = Array.isArray(data.SkillList) ? data.SkillList : []
  const items: MarketplaceItem[] = []
  const catCounts = new Map<string, number>()
  for (const raw of rows) {
    const row = asObject(raw)
    if (!row) continue
    const id = str(row.Name).trim()
    if (!id) continue
    const l1 = asObject(row.L1)
    const category = str(l1?.Name).trim()
    items.push({
      id,
      name: str(row.DisplayName).trim() || id,
      description: (str(row.DescriptionEn) || str(row.Description)).trim(),
      publisher: str(row.Path).trim(),
      categories: category ? [category] : [],
      sourceUrl: str(row.SourceURL).trim(),
      deployedUrl: '',
      deployedTransport: '',
      readme: '',
      metric: num(row.DownloadCount),
      isTop: num(row.IsTop),
      source: str(row.Source).trim(),
      tags: stringList(row.Tags)
    })
    if (category) catCounts.set(category, (catCounts.get(category) ?? 0) + 1)
  }
  const categories: MarketplaceCategory[] = Array.from(catCounts.entries())
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count)
  return { items, categories }
}

// ---- fetching ------------------------------------------------------------

async function fetchRemote(kind: MarketplaceKind): Promise<CacheRecord> {
  const endpoint = ENDPOINTS[kind]
  const response = await fetch(endpoint.url, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json, text/plain, */*',
      'User-Agent': USER_AGENT,
      Referer: endpoint.referer
    },
    body: endpoint.body,
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS)
  })
  if (!response.ok) {
    throw new Error(`ModelScope returned HTTP ${response.status}.`)
  }
  const payload = asObject(await response.json())
  if (!payload || num(payload.Code) !== 200) {
    throw new Error('ModelScope response was not in the expected shape.')
  }
  const data = asObject(payload.Data)
  if (!data) {
    throw new Error('ModelScope response had no data.')
  }
  const { items, categories } = kind === 'mcp' ? normalizeMcp(data) : normalizeSkill(data)
  if (items.length === 0) {
    throw new Error('ModelScope returned an empty catalog.')
  }
  return { fetchedAt: Date.now(), items, categories }
}

async function readDiskCache(kind: MarketplaceKind): Promise<CacheRecord | null> {
  try {
    const parsed = JSON.parse(await readFile(cachePath(kind), 'utf8')) as CacheRecord
    if (!Array.isArray(parsed?.items) || typeof parsed.fetchedAt !== 'number') return null
    if (!Array.isArray(parsed.categories)) parsed.categories = []
    return parsed
  } catch {
    return null
  }
}

async function writeDiskCache(kind: MarketplaceKind, record: CacheRecord): Promise<void> {
  try {
    await mkdir(cacheRoot(), { recursive: true })
    await writeFile(cachePath(kind), JSON.stringify(record), 'utf8')
  } catch {
    /* cache is best-effort */
  }
}

function toResult(kind: MarketplaceKind, record: CacheRecord, stale: boolean): MarketplaceCatalogResult {
  return { ok: true, kind, items: record.items, categories: record.categories, cachedAt: record.fetchedAt, stale }
}

/** Fresh memory → fresh disk → network; on network failure fall back to any stale cache. */
export async function getMarketplaceCatalog(kind: MarketplaceKind): Promise<MarketplaceCatalogResult> {
  const now = Date.now()
  const mem = memoryCache.get(kind)
  if (mem && now - mem.fetchedAt < CATALOG_TTL_MS) return toResult(kind, mem, false)

  const disk = mem ?? (await readDiskCache(kind))
  if (disk) {
    memoryCache.set(kind, disk)
    if (now - disk.fetchedAt < CATALOG_TTL_MS) return toResult(kind, disk, false)
  }

  return refreshMarketplaceCatalog(kind)
}

/** Force a network fetch, ignoring TTL; on failure fall back to stale cache. */
export async function refreshMarketplaceCatalog(kind: MarketplaceKind): Promise<MarketplaceCatalogResult> {
  try {
    const record = await fetchRemote(kind)
    memoryCache.set(kind, record)
    await writeDiskCache(kind, record)
    return toResult(kind, record, false)
  } catch (error) {
    const fallback = memoryCache.get(kind) ?? (await readDiskCache(kind))
    if (fallback) {
      memoryCache.set(kind, fallback)
      return toResult(kind, fallback, true)
    }
    return { ok: false, error: error instanceof Error ? error.message : String(error) }
  }
}

// ---- install helpers -----------------------------------------------------

/**
 * Convert a GitHub `tree` URL (as returned in a skill's SourceURL) into the raw
 * SKILL.md URL. Returns null for non-GitHub sources.
 * e.g. https://github.com/owner/repo/tree/main/a/b -> https://raw.githubusercontent.com/owner/repo/main/a/b/SKILL.md
 */
function rawSkillUrl(sourceUrl: string): string | null {
  const match = /^https?:\/\/github\.com\/([^/]+)\/([^/]+)\/tree\/([^/]+)\/(.+?)\/?$/.exec(sourceUrl)
  if (!match) return null
  const [, owner, repo, branch, path] = match
  return `https://raw.githubusercontent.com/${owner}/${repo}/${branch}/${path}/SKILL.md`
}

async function findCachedSkill(id: string): Promise<MarketplaceItem | null> {
  const record = memoryCache.get('skill') ?? (await readDiskCache('skill'))
  return record?.items.find((item) => item.id === id) ?? null
}

/** Fetch the real SKILL.md content from GitHub for a listed skill. */
export async function fetchSkillMarkdown(id: string): Promise<SkillMarkdownResult> {
  const item = await findCachedSkill(id)
  if (!item) return { ok: false, sourceUrl: '' }
  const raw = rawSkillUrl(item.sourceUrl)
  if (!raw) return { ok: false, sourceUrl: item.sourceUrl }
  try {
    const response = await fetch(raw, {
      headers: { 'User-Agent': USER_AGENT },
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS)
    })
    if (!response.ok) return { ok: false, sourceUrl: item.sourceUrl }
    const content = await response.text()
    if (!content.trim().startsWith('---')) return { ok: false, sourceUrl: item.sourceUrl }
    return { ok: true, content }
  } catch {
    return { ok: false, sourceUrl: item.sourceUrl }
  }
}

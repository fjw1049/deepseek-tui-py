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
const ENDPOINTS: Record<MarketplaceKind, { url: string; referer: string; body: Record<string, unknown> }> = {
  mcp: {
    url: 'https://www.modelscope.ai/api/v1/dolphin/mcpServers',
    referer: 'https://www.modelscope.ai/mcp',
    body: { PageSize: 30, PageNumber: 1, Query: '', Criterion: [] }
  },
  skill: {
    url: 'https://www.modelscope.ai/api/v1/dolphin/skills',
    referer: 'https://www.modelscope.ai/skills',
    // WithTopCollection:false returns the flat `SkillList` shape (vs the nested
    // SkillCollection when true) which is far cleaner to normalize.
    body: { PageSize: 30, PageNumber: 1, Query: '', Sort: 'Default', Criterion: [], WithTopCollection: false }
  }
}

const CATALOG_TTL_MS = 7 * 24 * 60 * 60 * 1000
const FETCH_TIMEOUT_MS = 15_000
const README_MAX = 40_000
// How many pages to pull per kind (PageSize 30 each → up to 90 items). The
// ModelScope API rejects PageSize much above ~100 and gets very slow when each
// row ships a full README, so we paginate the first few pages instead.
const MAX_PAGES = 3
const PAGE_SIZE = 30
const SKILL_MD_MAX = 200_000
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

/** Fetch one page of the catalog; returns the raw `Data` object. */
async function fetchPage(kind: MarketplaceKind, pageNumber: number): Promise<Record<string, unknown>> {
  const endpoint = ENDPOINTS[kind]
  const response = await fetch(endpoint.url, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json, text/plain, */*',
      'User-Agent': USER_AGENT,
      Referer: endpoint.referer
    },
    body: JSON.stringify({ ...endpoint.body, PageNumber: pageNumber }),
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
  return data
}

/**
 * Pull the first `MAX_PAGES` pages (PageSize 30 each) and merge them. Page 1
 * must succeed; later pages are best-effort — on failure or short page we stop
 * and keep whatever rows we already collected. The `FiledAgg` categories come
 * from page 1 (the renderer re-derives chips from items anyway).
 */
async function fetchRemote(kind: MarketplaceKind): Promise<CacheRecord> {
  // Page 1 must succeed — otherwise fall back to stale cache upstream.
  const firstData = await fetchPage(kind, 1)
  const firstRows =
    kind === 'mcp'
      ? (asObject(firstData.McpServer)?.McpServers ?? [])
      : (Array.isArray(firstData.SkillList) ? firstData.SkillList : [])
  const rows: unknown[] = Array.isArray(firstRows) ? [...firstRows] : []

  // Pages 2..MAX_PAGES are best-effort: on timeout/error or a short page, stop
  // and keep whatever we already collected rather than discarding page 1.
  for (let page = 2; page <= MAX_PAGES; page++) {
    if (rows.length > 0 && rows.length % PAGE_SIZE !== 0) break // last page already reached
    try {
      const data = await fetchPage(kind, page)
      const pageRows =
        kind === 'mcp'
          ? (asObject(data.McpServer)?.McpServers ?? [])
          : (Array.isArray(data.SkillList) ? data.SkillList : [])
      if (!Array.isArray(pageRows) || pageRows.length === 0) break
      rows.push(...pageRows)
      if (pageRows.length < PAGE_SIZE) break // last page reached
    } catch {
      break
    }
  }

  if (rows.length === 0) {
    throw new Error('ModelScope returned an empty catalog.')
  }
  // Reassemble a synthetic Data object with the combined rows + page-1 aggregation.
  const combined =
    kind === 'mcp'
      ? { McpServer: { McpServers: rows }, FiledAgg: firstData.FiledAgg ?? {} }
      : { SkillList: rows }
  const { items, categories } = kind === 'mcp' ? normalizeMcp(combined) : normalizeSkill(combined)
  // Pages can overlap a little (the API returned 3 dupes across 90 rows in
  // testing), so dedupe by id keeping first occurrence.
  const seen = new Set<string>()
  const deduped = items.filter((item) => {
    if (seen.has(item.id)) return false
    seen.add(item.id)
    return true
  })
  if (deduped.length === 0) {
    throw new Error('ModelScope returned an empty catalog.')
  }
  return { fetchedAt: Date.now(), items: deduped, categories }
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
 * Convert a GitHub `tree` URL (as returned in a skill's SourceURL) into
 * candidate raw SKILL.md URLs. Returns multiple candidates because branch
 * names may contain slashes (e.g. `feature/foo`), making the split between
 * branch and path ambiguous in `tree/<branch>/<path>`. Callers fetch each
 * candidate and keep the first that returns a valid SKILL.md.
 * e.g. https://github.com/owner/repo/tree/main/a/b -> https://raw.githubusercontent.com/owner/repo/main/a/b/SKILL.md
 */
function rawSkillUrlCandidates(sourceUrl: string): string[] {
  const match = /^https?:\/\/github\.com\/([^/]+)\/([^/]+)\/tree\/(.+)$/.exec(sourceUrl)
  if (!match) return []
  const [, owner, repo, rest] = match
  const segments = rest.split('/').filter(Boolean)
  const candidates: string[] = []
  // Shortest-branch-first: the common case is a single-segment branch
  // (`main`/`master`), so try that first and fall back to longer branches
  // only if it 404s. This keeps the hot path at one request while still
  // resolving slash-branches (`feature/foo/skills/bar`).
  for (let i = 1; i < segments.length; i++) {
    const branch = segments.slice(0, i).join('/')
    const path = segments.slice(i).join('/')
    if (!branch || !path) continue
    candidates.push(`https://raw.githubusercontent.com/${owner}/${repo}/${branch}/${path}/SKILL.md`)
  }
  return candidates
}

async function findCachedSkill(id: string): Promise<MarketplaceItem | null> {
  const record = memoryCache.get('skill') ?? (await readDiskCache('skill'))
  return record?.items.find((item) => item.id === id) ?? null
}

/** Fetch the real SKILL.md content from GitHub for a listed skill. */
export async function fetchSkillMarkdown(id: string): Promise<SkillMarkdownResult> {
  const item = await findCachedSkill(id)
  if (!item) return { ok: false, sourceUrl: '' }
  const candidates = rawSkillUrlCandidates(item.sourceUrl)
  if (candidates.length === 0) return { ok: false, sourceUrl: item.sourceUrl }
  try {
    for (const raw of candidates) {
      // Sequential probes are intentional: stop at the first valid SKILL.md.
      const response = await fetch(raw, {
        headers: { 'User-Agent': USER_AGENT },
        signal: AbortSignal.timeout(FETCH_TIMEOUT_MS)
      })
      if (!response.ok) continue
      // Cap the body so a malicious or gigantic SKILL.md can't exhaust main
      // process memory or blow up the IPC channel to the renderer.
      const text = await response.text()
      if (text.length > SKILL_MD_MAX) continue
      if (!text.trim().startsWith('---')) continue
      return { ok: true, content: text }
    }
    return { ok: false, sourceUrl: item.sourceUrl }
  } catch {
    return { ok: false, sourceUrl: item.sourceUrl }
  }
}

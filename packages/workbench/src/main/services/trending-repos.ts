import type { TrendingPeriod, TrendingRepo, TrendingResult } from '../../shared/ds-gui-api'

const TRENDING_URLS: Record<TrendingPeriod, string> = {
  daily: 'https://trendshift.io/',
  weekly: 'https://trendshift.io/weekly',
  monthly: 'https://trendshift.io/monthly'
}

const CACHE_TTL_MS = 10 * 60 * 1_000
const MAX_REPOS = 20
const USER_AGENT =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'

const cache = new Map<TrendingPeriod, { result: TrendingResult; fetchedAt: number }>()

type JsonObject = Record<string, unknown>
type RepoSignals = {
  stars: string
  gained: string
  topics: string[]
  isNew: boolean
}

function asObject(value: unknown): JsonObject | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as JsonObject
    : null
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is string => typeof item === 'string')
}

function decodeHtml(value: string): string {
  return value
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&#39;/g, "'")
}

function plainText(html: string): string {
  return decodeHtml(
    html
      .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, ' ')
      .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, ' ')
      .replace(/<!--\s*\/?\s*-->/g, ' ')
      .replace(/<[^>]+>/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
  )
}

function isRepoName(value: string): boolean {
  return /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(value.trim())
}

function extractTopics(block: string): string[] {
  const topics = new Set<string>()
  const topicPattern = /<a[^>]+href="\/topics\/[^"]+"[^>]*>([\s\S]*?)<\/a>/gi
  for (const match of block.matchAll(topicPattern)) {
    const topic = plainText(match[1] ?? '').replace(/^#/, '').trim()
    if (topic) topics.add(topic)
  }
  return Array.from(topics).slice(0, 4)
}

function extractDescription(block: string, name: string): string {
  const text = plainText(block)
  const withoutName = text.replace(name, ' ')
  const sentences = withoutName
    .split(/\s{2,}| (?=\d+(?:\.\d+)?k?\s+\d+(?:\.\d+)?k? )/i)
    .map((item) => item.trim())
    .filter(Boolean)

  const candidate = sentences.find((item) => {
    if (item.length < 24) return false
    if (/^(NEW|\d+(?:\.\d+)?k?|\d{4})\b/i.test(item)) return false
    if (/^(Daily|Weekly|Monthly|Trending|GitHub|Topics)\b/i.test(item)) return false
    return !item.includes('Advertise on Trendshift')
  })
  return candidate?.slice(0, 260) ?? ''
}

function extractNumbers(block: string, name: string): string[] {
  const text = plainText(block).replace(name, ' ')
  const numbers = text.match(/\b\d+(?:\.\d+)?k?\b/gi) ?? []
  return numbers.filter((value) => !/^20\d{2}$/.test(value)).slice(0, 2)
}

function extractRepoSignals(html: string): Map<string, RepoSignals> {
  const repoPattern = /<a[^>]+href="\/repositories\/\d+"[^>]*>([\s\S]*?)<\/a>/gi
  const matches = Array.from(html.matchAll(repoPattern))
  const signals = new Map<string, RepoSignals>()

  for (let index = 0; index < matches.length; index += 1) {
    const match = matches[index]
    const name = plainText(match[1] ?? '')
    if (!isRepoName(name) || signals.has(name)) continue

    const blockStart = match.index ?? 0
    const nextMatch = matches.slice(index + 1).find((candidate) => {
      const candidateName = plainText(candidate[1] ?? '')
      return isRepoName(candidateName) && candidateName !== name
    })
    const blockEnd = nextMatch?.index ?? html.length
    const block = html.slice(blockStart, blockEnd)
    const numbers = extractNumbers(block, name)
    const topics = extractTopics(block)
    if (numbers.length === 0 && topics.length === 0) continue

    signals.set(name, {
      stars: numbers[0] ?? '',
      gained: numbers[1] ?? '',
      topics,
      isNew: /\bNEW\b[\s\S]{0,80}\b20\d{2}\b/i.test(block)
    })
  }

  return signals
}

function parseStructuredRepos(html: string, signals: Map<string, RepoSignals>): TrendingRepo[] {
  const scripts = html.matchAll(
    /<script[^>]+type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/gi
  )
  for (const script of scripts) {
    let data: unknown
    try {
      data = JSON.parse(script[1] ?? '')
    } catch {
      continue
    }
    const root = asObject(data)
    const items = Array.isArray(root?.itemListElement) ? root.itemListElement : []
    const repos: TrendingRepo[] = []

    for (const entry of items) {
      const record = asObject(entry)
      const item = asObject(record?.item)
      const name = stringValue(item?.name).trim()
      if (!isRepoName(name)) continue

      const signal = signals.get(name)
      repos.push({
        rank: typeof record?.position === 'number' ? record.position : repos.length + 1,
        name,
        description: stringValue(item?.description).trim(),
        stars: signal?.stars ?? '',
        gained: signal?.gained ?? '',
        topics: signal?.topics.length ? signal.topics : stringList(item?.keywords).slice(0, 4),
        isNew: signal?.isNew ?? false,
        url: stringValue(item?.codeRepository) || stringValue(item?.url) || `https://github.com/${name}`
      })
      if (repos.length >= MAX_REPOS) break
    }

    if (repos.length > 0) return repos
  }

  return []
}

function parseTrendingRepos(html: string): TrendingRepo[] {
  const signals = extractRepoSignals(html)
  const structuredRepos = parseStructuredRepos(html, signals)
  if (structuredRepos.length > 0) return structuredRepos

  const repos: TrendingRepo[] = []
  for (const [name, signal] of signals) {
    repos.push({
      rank: repos.length + 1,
      name,
      description: extractDescription(html, name),
      stars: signal.stars,
      gained: signal.gained,
      topics: signal.topics,
      isNew: signal.isNew,
      url: `https://github.com/${name}`
    })
    if (repos.length >= MAX_REPOS) break
  }

  return repos
}

export async function getTrendingRepos(period: TrendingPeriod): Promise<TrendingResult> {
  const cached = cache.get(period)
  const now = Date.now()
  if (cached && now - cached.fetchedAt < CACHE_TTL_MS) {
    return cached.result
  }

  try {
    const response = await fetch(TRENDING_URLS[period], {
      headers: { 'User-Agent': USER_AGENT },
      signal: AbortSignal.timeout(10_000)
    })
    if (!response.ok) {
      return { ok: false, error: `TrendShift returned HTTP ${response.status}.` }
    }

    const repos = parseTrendingRepos(await response.text())
    if (repos.length === 0) {
      return { ok: false, error: 'TrendShift page did not contain repositories.' }
    }

    const result: TrendingResult = { ok: true, repos, period, cachedAt: now }
    cache.set(period, { result, fetchedAt: now })
    return result
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) }
  }
}

import { useEffect, useState } from 'react'

export type ThreadUsageSummary = {
  inputTokens: number
  outputTokens: number
  reasoningTokens: number
  cachedTokens: number
  cacheMissTokens: number
  cacheHitRate: number | null
  totalTokens: number
  costUsd: number | null
  costCny: number | null
  tokenEconomySavingsTokens: number
  turns: number
}

export type ThreadUsageState = {
  usage: ThreadUsageSummary | null
  loading: boolean
  loaded: boolean
}

function usageNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function hasFiniteNumber(record: Record<string, unknown>, key: string): boolean {
  return typeof record[key] === 'number' && Number.isFinite(record[key])
}

function usageRate(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : null
}

export function formatCompactNumber(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`
  return new Intl.NumberFormat().format(value)
}

function isChineseLocale(locale?: string): boolean {
  const normalized = (locale ?? '').trim().toLowerCase()
  return normalized === 'zh' || normalized.startsWith('zh-')
}

function fallbackLocale(): string {
  return typeof navigator !== 'undefined' ? navigator.language : 'en'
}

function formatMoneyValue(value: number): string {
  const safeValue = Number.isFinite(value) ? value : 0
  if (safeValue > 0 && safeValue < 0.0001) return '<0.0001'
  return safeValue.toFixed(safeValue >= 1 ? 2 : 4)
}

export function formatCost(
  costUsd: number | null | undefined,
  locale = fallbackLocale(),
  costCny?: number | null
): string {
  const hasUsd = typeof costUsd === 'number' && Number.isFinite(costUsd) && costUsd > 0
  const hasCny = typeof costCny === 'number' && Number.isFinite(costCny) && costCny > 0
  const usdValue = hasUsd ? costUsd : null
  const cnyValue = hasCny ? costCny : null
  if (!hasUsd && !hasCny) return '-'
  if (isChineseLocale(locale)) {
    const value = cnyValue ?? (usdValue ?? 0) * 7.2
    return `￥${formatMoneyValue(value)}`
  }
  if (usdValue != null) return `$${formatMoneyValue(usdValue)}`
  return `￥${formatMoneyValue(cnyValue ?? 0)}`
}

export function formatPercent(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return '-'
  const percent = Math.max(0, Math.min(100, value * 100))
  if (percent === 0 || percent >= 10) return `${Math.round(percent)}%`
  return `${percent.toFixed(1)}%`
}

export async function loadThreadUsage(threadId: string): Promise<ThreadUsageSummary | null> {
  if (typeof window.dsGui?.runtimeRequest !== 'function') return null
  const params = new URLSearchParams({
    group_by: 'thread',
    thread_id: threadId
  })
  const r = await window.dsGui.runtimeRequest(`/v1/usage?${params.toString()}`, 'GET')
  if (!r.ok || !r.body.trim()) return null
  let parsed: { buckets?: Array<Record<string, unknown>> }
  try {
    parsed = JSON.parse(r.body) as { buckets?: Array<Record<string, unknown>> }
  } catch {
    return null
  }
  const bucket = parsed.buckets?.find((item) => {
    const candidates = [item.thread_id, item.key, item.id, item.label]
    return candidates.some((candidate) => candidate === threadId)
  })
  if (!bucket) return null
  const inputTokens = usageNumber(bucket.input_tokens)
  const outputTokens = usageNumber(bucket.output_tokens)
  const reasoningTokens = usageNumber(bucket.reasoning_tokens)
  const bucketCacheHitRate = usageRate(bucket.cache_hit_rate)
  const hasBucketCacheTelemetry = bucketCacheHitRate !== null
  const cachedTokens = hasBucketCacheTelemetry ? usageNumber(bucket.cached_tokens) : 0
  const cacheMissTokens = hasBucketCacheTelemetry ? usageNumber(bucket.cache_miss_tokens) : 0
  const cacheHitRate = bucketCacheHitRate
  const totalTokens = inputTokens + outputTokens
  const rawCostUsd = hasFiniteNumber(bucket, 'cost_usd') ? usageNumber(bucket.cost_usd) : null
  const rawCostCny = hasFiniteNumber(bucket, 'cost_cny') ? usageNumber(bucket.cost_cny) : null
  const costUsd = rawCostUsd != null && rawCostUsd > 0 ? rawCostUsd : null
  const costCny = rawCostCny != null && rawCostCny > 0 ? rawCostCny : null
  const tokenEconomySavingsTokens = usageNumber(bucket.token_economy_savings_tokens)
  const turns = usageNumber(bucket.turns)
  if (
    totalTokens <= 0 &&
    cachedTokens <= 0 &&
    (costUsd ?? 0) <= 0 &&
    (costCny ?? 0) <= 0 &&
    tokenEconomySavingsTokens <= 0 &&
    turns <= 0
  ) {
    return null
  }
  return {
    inputTokens,
    outputTokens,
    reasoningTokens,
    cachedTokens,
    cacheMissTokens,
    cacheHitRate,
    totalTokens,
    costUsd,
    costCny,
    tokenEconomySavingsTokens,
    turns
  }
}

export function useThreadUsageState(
  threadId: string | null | undefined,
  enabled: boolean,
  refreshKey: unknown,
  pollWhileBusy = false
): ThreadUsageState {
  const [state, setState] = useState<ThreadUsageState>({
    usage: null,
    loading: false,
    loaded: false
  })

  useEffect(() => {
    let cancelled = false
    if (!threadId || !enabled) {
      setState({ usage: null, loading: false, loaded: false })
      return
    }
    const refresh = (): void => {
      void loadThreadUsage(threadId)
        .then((usage) => {
          if (!cancelled) setState({ usage, loading: false, loaded: true })
        })
        .catch(() => {
          if (!cancelled) setState({ usage: null, loading: false, loaded: true })
        })
    }
    setState((current) => ({ ...current, loading: true }))
    refresh()
    const interval = pollWhileBusy ? window.setInterval(refresh, 2_000) : undefined
    return () => {
      cancelled = true
      if (interval !== undefined) window.clearInterval(interval)
    }
  }, [enabled, pollWhileBusy, refreshKey, threadId])

  return state
}

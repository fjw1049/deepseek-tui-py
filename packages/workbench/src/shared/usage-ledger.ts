import { decodeModelRef, encodeModelRef } from './model-ref'

export const USAGE_LEDGER_SCHEMA_VERSION = 1
export const USAGE_RETENTION_DAYS = 90
/** Longest window we keep and can query (used by the activity heatmap). */
export const USAGE_MAX_RANGE_DAYS = 365

export type UsageRange = '7d' | '30d' | '90d' | '1y'

export type ModelUsageBucket = {
  model: string
  inputTokens: number
  outputTokens: number
  totalTokens: number
  costUsd: number | null
  costCny: number | null
  turns: number
}

export type ModelUsageSummary = {
  buckets: ModelUsageBucket[]
  totals: Omit<ModelUsageBucket, 'model'>
}

export type UsageLedgerBucket = {
  model: string
  input_tokens: number
  output_tokens: number
  total_tokens: number
  cost_usd: number
  cost_cny: number
  turns: number
}

export type UsageLedgerDay = {
  models: Record<string, UsageLedgerBucket>
  totals: Omit<UsageLedgerBucket, 'model'>
}

export type UsageLedgerV1 = {
  schemaVersion: number
  updatedAt: string
  retentionDays: number
  processedTurnIds: Record<string, string>
  days: Record<string, UsageLedgerDay>
}

export type UsageDailyPoint = {
  day: string
  label: string
  totalTokens: number
  segments: Array<{ model: string; tokens: number }>
}

export type UsageQueryResult = {
  range: UsageRange
  daily: UsageDailyPoint[]
  summary: ModelUsageSummary | null
  /** Last day included in the window (local YYYY-MM-DD). */
  asOfDay: string
}

function usageNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function emptyBucket(model: string): UsageLedgerBucket {
  return {
    model,
    input_tokens: 0,
    output_tokens: 0,
    total_tokens: 0,
    cost_usd: 0,
    cost_cny: 0,
    turns: 0
  }
}

export function emptyUsageLedger(): UsageLedgerV1 {
  return {
    schemaVersion: USAGE_LEDGER_SCHEMA_VERSION,
    updatedAt: new Date().toISOString(),
    retentionDays: USAGE_RETENTION_DAYS,
    processedTurnIds: {},
    days: {}
  }
}

export function normalizeUsageLedger(raw: unknown): UsageLedgerV1 {
  if (!raw || typeof raw !== 'object') return emptyUsageLedger()
  const parsed = raw as Partial<UsageLedgerV1>
  if (parsed.schemaVersion !== USAGE_LEDGER_SCHEMA_VERSION) return emptyUsageLedger()
  return {
    schemaVersion: USAGE_LEDGER_SCHEMA_VERSION,
    updatedAt: typeof parsed.updatedAt === 'string' ? parsed.updatedAt : new Date().toISOString(),
    retentionDays: USAGE_RETENTION_DAYS,
    processedTurnIds:
      parsed.processedTurnIds && typeof parsed.processedTurnIds === 'object'
        ? parsed.processedTurnIds
        : {},
    days: parsed.days && typeof parsed.days === 'object' ? parsed.days : {}
  }
}

function localDayKey(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function rangeStartDay(range: UsageRange, referenceDate: Date): string {
  const days =
    range === '7d'
      ? 6
      : range === '30d'
        ? 29
        : range === '90d'
          ? USAGE_RETENTION_DAYS - 1
          : USAGE_MAX_RANGE_DAYS - 1
  const start = new Date(referenceDate)
  start.setHours(0, 0, 0, 0)
  start.setDate(start.getDate() - days)
  return localDayKey(start)
}

function formatDayLabel(day: string, locale: string): string {
  const parsed = new Date(`${day}T12:00:00`)
  if (Number.isNaN(parsed.getTime())) return day
  return parsed.toLocaleDateString(locale, { month: 'numeric', day: 'numeric' })
}

function bucketToSummaryBucket(model: string, bucket: UsageLedgerBucket): ModelUsageBucket {
  const costUsd = bucket.cost_usd
  const costCny = bucket.cost_cny
  return {
    model,
    inputTokens: bucket.input_tokens,
    outputTokens: bucket.output_tokens,
    totalTokens: bucket.total_tokens,
    costUsd: costUsd > 0 ? costUsd : null,
    costCny: costCny > 0 ? costCny : null,
    turns: bucket.turns
  }
}

function mergeSummaryBucket(target: UsageLedgerBucket, source: UsageLedgerBucket): void {
  target.input_tokens += source.input_tokens
  target.output_tokens += source.output_tokens
  target.total_tokens += source.total_tokens
  target.cost_usd += source.cost_usd
  target.cost_cny += source.cost_cny
  target.turns += source.turns
}

export function queryUsageLedger(
  ledger: UsageLedgerV1,
  range: UsageRange,
  locale = 'en',
  referenceDate = new Date()
): UsageQueryResult {
  const anchor = new Date(referenceDate)
  anchor.setHours(0, 0, 0, 0)
  const startDay = rangeStartDay(range, anchor)
  const merged: Record<string, UsageLedgerBucket> = {}
  const daily: UsageDailyPoint[] = []

  const dayCount =
    range === '7d'
      ? 7
      : range === '30d'
        ? 30
        : range === '90d'
          ? USAGE_RETENTION_DAYS
          : USAGE_MAX_RANGE_DAYS
  for (let offset = dayCount - 1; offset >= 0; offset -= 1) {
    const date = new Date(anchor)
    date.setDate(anchor.getDate() - offset)
    const day = localDayKey(date)
    if (day < startDay) continue
    const dayBucket = ledger.days[day]
    const segments: Array<{ model: string; tokens: number }> = []
    let totalTokens = 0
    if (dayBucket?.models) {
      for (const [model, bucket] of Object.entries(dayBucket.models)) {
        if (bucket.total_tokens <= 0) continue
        segments.push({ model, tokens: bucket.total_tokens })
        totalTokens += bucket.total_tokens
        const target = merged[model] ?? emptyBucket(model)
        mergeSummaryBucket(target, bucket)
        merged[model] = target
      }
    }
    segments.sort((a, b) => b.tokens - a.tokens || a.model.localeCompare(b.model))
    daily.push({
      day,
      label: formatDayLabel(day, locale),
      totalTokens,
      segments
    })
  }

  const buckets = Object.entries(merged)
    .map(([model, bucket]) => bucketToSummaryBucket(model, bucket))
    .sort((a, b) => b.totalTokens - a.totalTokens || a.model.localeCompare(b.model))

  if (buckets.length === 0) {
    return { range, daily, summary: null, asOfDay: localDayKey(anchor) }
  }

  const totals = buckets.reduce(
    (acc, bucket) => ({
      inputTokens: acc.inputTokens + bucket.inputTokens,
      outputTokens: acc.outputTokens + bucket.outputTokens,
      totalTokens: acc.totalTokens + bucket.totalTokens,
      costUsd: (acc.costUsd ?? 0) + (bucket.costUsd ?? 0),
      costCny: (acc.costCny ?? 0) + (bucket.costCny ?? 0),
      turns: acc.turns + bucket.turns
    }),
    {
      inputTokens: 0,
      outputTokens: 0,
      totalTokens: 0,
      costUsd: 0,
      costCny: 0,
      turns: 0
    }
  )

  return {
    range,
    daily,
    summary: {
      buckets,
      totals: {
        inputTokens: totals.inputTokens,
        outputTokens: totals.outputTokens,
        totalTokens: totals.totalTokens,
        costUsd: totals.costUsd > 0 ? totals.costUsd : null,
        costCny: totals.costCny > 0 ? totals.costCny : null,
        turns: totals.turns
      }
    },
    asOfDay: localDayKey(anchor)
  }
}

export function pruneUsageProvider(ledger: UsageLedgerV1, providerId: string): UsageLedgerV1 {
  const provider = providerId.trim()
  if (!provider) return ledger
  const next = normalizeUsageLedger(structuredClone(ledger))
  const shouldDrop = (modelRef: string): boolean =>
    decodeModelRef(modelRef).providerId === provider
  for (const dayBucket of Object.values(next.days)) {
    for (const modelRef of Object.keys(dayBucket.models)) {
      if (shouldDrop(modelRef)) delete dayBucket.models[modelRef]
    }
  }
  return next
}

export function pruneUsageEndpointModel(
  ledger: UsageLedgerV1,
  providerId: string,
  modelId: string
): UsageLedgerV1 {
  const targetRef = encodeModelRef(providerId, modelId)
  const next = normalizeUsageLedger(structuredClone(ledger))
  for (const dayBucket of Object.values(next.days)) {
    delete dayBucket.models[targetRef]
  }
  return next
}

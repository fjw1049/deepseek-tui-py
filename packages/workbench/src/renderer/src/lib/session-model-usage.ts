import { decodeModelRef, encodeModelRef } from '@shared/model-ref'
import type { ModelUsageSummary } from '../hooks/use-model-usage'

export type SessionModelUsageBucket = {
  model: string
  inputTokens: number
  outputTokens: number
  totalTokens: number
  costUsd: number
  costCny: number
  turns: number
}

export type SessionModelUsageMap = Record<string, SessionModelUsageBucket>

function usageNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function usageFloat(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function emptyBucket(model: string): SessionModelUsageBucket {
  return {
    model,
    inputTokens: 0,
    outputTokens: 0,
    totalTokens: 0,
    costUsd: 0,
    costCny: 0,
    turns: 0
  }
}

function mergeUsageBucket(
  session: SessionModelUsageMap,
  modelId: string,
  bucket: Record<string, unknown>
): void {
  const normalized = modelId.trim() || 'unknown'
  const target = session[normalized] ?? emptyBucket(normalized)
  const inputTokens = usageNumber(bucket.input_tokens ?? bucket.prompt_tokens)
  const outputTokens = usageNumber(bucket.output_tokens ?? bucket.completion_tokens)
  target.inputTokens += inputTokens
  target.outputTokens += outputTokens
  target.totalTokens += usageNumber(bucket.total_tokens) || inputTokens + outputTokens
  target.costUsd += usageFloat(bucket.cost_usd)
  target.costCny += usageFloat(bucket.cost_cny)
  target.turns += Math.max(1, usageNumber(bucket.turns))
  session[normalized] = target
}

export function accumulateSessionModelUsage(
  session: SessionModelUsageMap,
  turnUsage: Record<string, unknown> | null | undefined,
  fallbackModel: string
): SessionModelUsageMap {
  if (!turnUsage || typeof turnUsage !== 'object') return session
  const next: SessionModelUsageMap = { ...session }
  const models = turnUsage.models
  if (models && typeof models === 'object' && !Array.isArray(models)) {
    for (const [modelId, bucket] of Object.entries(models)) {
      if (bucket && typeof bucket === 'object') {
        mergeUsageBucket(next, modelId, bucket as Record<string, unknown>)
      }
    }
    return next
  }
  mergeUsageBucket(next, fallbackModel.trim() || 'unknown', turnUsage)
  return next
}

export function pruneSessionModelUsageRef(
  session: SessionModelUsageMap,
  modelRef: string
): SessionModelUsageMap {
  const normalized = modelRef.trim()
  if (!normalized || !(normalized in session)) return session
  const next = { ...session }
  delete next[normalized]
  return next
}

export function pruneSessionModelUsageProvider(
  session: SessionModelUsageMap,
  providerId: string
): SessionModelUsageMap {
  const provider = providerId.trim()
  if (!provider) return session
  const next: SessionModelUsageMap = {}
  for (const [modelRef, bucket] of Object.entries(session)) {
    if (decodeModelRef(modelRef).providerId === provider) continue
    next[modelRef] = bucket
  }
  return next
}

export function pruneSessionModelUsageEndpointModel(
  session: SessionModelUsageMap,
  providerId: string,
  modelId: string
): SessionModelUsageMap {
  return pruneSessionModelUsageRef(session, encodeModelRef(providerId, modelId))
}

export function toModelUsageSummary(session: SessionModelUsageMap): ModelUsageSummary | null {
  const buckets = Object.values(session).sort(
    (a, b) => b.totalTokens - a.totalTokens || a.model.localeCompare(b.model)
  )
  if (buckets.length === 0) return null
  const totals = buckets.reduce(
    (acc, bucket) => ({
      inputTokens: acc.inputTokens + bucket.inputTokens,
      outputTokens: acc.outputTokens + bucket.outputTokens,
      totalTokens: acc.totalTokens + bucket.totalTokens,
      costUsd: acc.costUsd + bucket.costUsd,
      costCny: acc.costCny + bucket.costCny,
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
    buckets: buckets.map((bucket) => ({
      model: bucket.model,
      inputTokens: bucket.inputTokens,
      outputTokens: bucket.outputTokens,
      totalTokens: bucket.totalTokens,
      costUsd: bucket.costUsd > 0 ? bucket.costUsd : null,
      costCny: bucket.costCny > 0 ? bucket.costCny : null,
      turns: bucket.turns
    })),
    totals: {
      inputTokens: totals.inputTokens,
      outputTokens: totals.outputTokens,
      totalTokens: totals.totalTokens,
      costUsd: totals.costUsd > 0 ? totals.costUsd : null,
      costCny: totals.costCny > 0 ? totals.costCny : null,
      turns: totals.turns
    }
  }
}

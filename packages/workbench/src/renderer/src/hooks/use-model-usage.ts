import { useEffect, useState } from 'react'
import { formatCompactNumber, formatCost } from './use-thread-usage'
import type { ModelUsageBucket, ModelUsageSummary } from '@shared/usage-ledger'

export type { ModelUsageBucket, ModelUsageSummary }

export type ModelUsageState = {
  usage: ModelUsageSummary | null
  loading: boolean
  loaded: boolean
  error: string | null
}

function usageNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function parseBucket(raw: Record<string, unknown>): ModelUsageBucket {
  const inputTokens = usageNumber(raw.input_tokens)
  const outputTokens = usageNumber(raw.output_tokens)
  const totalTokens = usageNumber(raw.total_tokens) || inputTokens + outputTokens
  const costUsdRaw = usageNumber(raw.cost_usd)
  const costCnyRaw = usageNumber(raw.cost_cny)
  return {
    model: typeof raw.model === 'string' && raw.model.trim() ? raw.model.trim() : 'unknown',
    inputTokens,
    outputTokens,
    totalTokens,
    costUsd: costUsdRaw > 0 ? costUsdRaw : null,
    costCny: costCnyRaw > 0 ? costCnyRaw : null,
    turns: usageNumber(raw.turns)
  }
}

function parseUsagePayload(body: string): ModelUsageSummary | null {
  let parsed: { buckets?: Array<Record<string, unknown>>; totals?: Record<string, unknown> }
  try {
    parsed = JSON.parse(body) as {
      buckets?: Array<Record<string, unknown>>
      totals?: Record<string, unknown>
    }
  } catch {
    return null
  }
  const buckets = (parsed.buckets ?? []).map(parseBucket)
  const totalsRaw = parsed.totals ?? {}
  const totals = parseBucket({ ...totalsRaw, model: 'total' })
  if (buckets.length <= 0 && totals.totalTokens <= 0) return null
  return {
    buckets,
    totals: {
      inputTokens: totals.inputTokens,
      outputTokens: totals.outputTokens,
      totalTokens: totals.totalTokens,
      costUsd: totals.costUsd,
      costCny: totals.costCny,
      turns: totals.turns
    }
  }
}

export async function loadSessionModelUsage(): Promise<{
  usage: ModelUsageSummary | null
  error: string | null
}> {
  if (typeof window.dsGui?.runtimeRequest !== 'function') {
    return { usage: null, error: 'runtime_unavailable' }
  }
  const params = new URLSearchParams({
    group_by: 'model',
    scope: 'session'
  })
  const r = await window.dsGui.runtimeRequest(`/v1/usage?${params.toString()}`, 'GET')
  if (!r.ok) {
    let message = `HTTP ${r.status}`
    try {
      const parsed = JSON.parse(r.body) as { message?: string; error?: string }
      message = parsed.message ?? parsed.error ?? message
    } catch {
      if (r.body.trim()) message = r.body.trim()
    }
    return { usage: null, error: message }
  }
  if (!r.body.trim()) return { usage: null, error: null }
  return { usage: parseUsagePayload(r.body), error: null }
}

export function useSessionModelUsageState(
  enabled: boolean,
  refreshKey: unknown,
  pollWhileBusy = false
): ModelUsageState {
  const [state, setState] = useState<ModelUsageState>({
    usage: null,
    loading: false,
    loaded: false,
    error: null
  })

  useEffect(() => {
    let cancelled = false
    if (!enabled) {
      setState({ usage: null, loading: false, loaded: false, error: null })
      return
    }
    const refresh = (): void => {
      void loadSessionModelUsage()
        .then(({ usage, error }) => {
          if (!cancelled) setState({ usage, loading: false, loaded: true, error })
        })
        .catch((e) => {
          if (!cancelled) {
            setState({
              usage: null,
              loading: false,
              loaded: true,
              error: e instanceof Error ? e.message : String(e)
            })
          }
        })
    }
    setState((current) => ({ ...current, loading: true, error: null }))
    refresh()
    const intervalMs = pollWhileBusy ? 2_000 : 4_000
    const interval = window.setInterval(refresh, intervalMs)
    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [enabled, pollWhileBusy, refreshKey])

  return state
}

export { formatCompactNumber, formatCost }

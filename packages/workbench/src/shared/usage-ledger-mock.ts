import {
  USAGE_LEDGER_SCHEMA_VERSION,
  USAGE_RETENTION_DAYS,
  type UsageLedgerBucket,
  type UsageLedgerDay,
  type UsageLedgerV1
} from './usage-ledger'

/** One stretch of usage for a model — mimics real adoption / abandonment arcs. */
type ModelUsageArc = {
  model: string
  /** Inclusive: oldest day in window (e.g. 89 = 90 days ago). */
  fromDaysAgo: number
  /** Inclusive: 0 = today. */
  toDaysAgo: number
  /** Fraction of days in range that have any usage (0–1). */
  activeRate: number
  /** Typical input tokens on an active day. */
  inputPerActiveDay: number
  outputRatio: number
  turnsPerActiveDay: number
  costUsdPer1k: number
  costCnyPer1k: number
  /** Deterministic salt so models don't all fire on the same days. */
  salt: number
  /** daysAgo values inside the arc that get a one-off heavy session. */
  spikeDaysAgo?: number[]
  spikeMultiplier?: number
}

/**
 * Models from the user's composer list. Built-in DeepSeek ids are bare;
 * third-party gateway models use ``qingyun::`` (matches typical endpoint storage).
 */
const MODEL_ARCS: ModelUsageArc[] = [
  // Daily driver — steady but not every single day.
  {
    model: 'deepseek-v4-pro',
    fromDaysAgo: 89,
    toDaysAgo: 0,
    activeRate: 0.62,
    inputPerActiveDay: 38_000,
    outputRatio: 0.035,
    turnsPerActiveDay: 6,
    costUsdPer1k: 0.002,
    costCnyPer1k: 0.014,
    salt: 11,
    spikeDaysAgo: [2, 18, 41, 67],
    spikeMultiplier: 2.8
  },
  // Cheap workhorse — high volume, many short turns.
  {
    model: 'deepseek-v4-flash',
    fromDaysAgo: 89,
    toDaysAgo: 0,
    activeRate: 0.78,
    inputPerActiveDay: 96_000,
    outputRatio: 0.055,
    turnsPerActiveDay: 22,
    costUsdPer1k: 0.00035,
    costCnyPer1k: 0.0025,
    salt: 23,
    spikeDaysAgo: [0, 7, 33],
    spikeMultiplier: 1.6
  },
  // GLM 5.1 — used for a while, then dropped before sunset.
  {
    model: 'qingyun::glm-5.1',
    fromDaysAgo: 82,
    toDaysAgo: 31,
    activeRate: 0.48,
    inputPerActiveDay: 52_000,
    outputRatio: 0.04,
    turnsPerActiveDay: 4,
    costUsdPer1k: 0.0018,
    costCnyPer1k: 0.013,
    salt: 37
  },
  // GLM 5.2 — picked up after 5.1, becoming the main Zhipu choice.
  {
    model: 'qingyun::glm-5.2',
    fromDaysAgo: 28,
    toDaysAgo: 0,
    activeRate: 0.58,
    inputPerActiveDay: 118_000,
    outputRatio: 0.045,
    turnsPerActiveDay: 5,
    costUsdPer1k: 0.0022,
    costCnyPer1k: 0.016,
    salt: 41,
    spikeDaysAgo: [4, 12, 21],
    spikeMultiplier: 2.2
  },
  // Doubao pro — one intense two-week sprint, then abandoned.
  {
    model: 'qingyun::doubao-seed-2.0-pro',
    fromDaysAgo: 54,
    toDaysAgo: 39,
    activeRate: 0.92,
    inputPerActiveDay: 210_000,
    outputRatio: 0.05,
    turnsPerActiveDay: 8,
    costUsdPer1k: 0.0025,
    costCnyPer1k: 0.018,
    salt: 53
  },
  // Doubao lite — occasional dabbling, very light.
  {
    model: 'qingyun::doubao-seed-2.0-lite',
    fromDaysAgo: 70,
    toDaysAgo: 0,
    activeRate: 0.14,
    inputPerActiveDay: 6_500,
    outputRatio: 0.07,
    turnsPerActiveDay: 2,
    costUsdPer1k: 0.0005,
    costCnyPer1k: 0.0035,
    salt: 59
  },
  // Doubao code — focused coding sprint ~3 weeks, then stopped.
  {
    model: 'qingyun::doubao-seed-code',
    fromDaysAgo: 36,
    toDaysAgo: 19,
    activeRate: 0.72,
    inputPerActiveDay: 88_000,
    outputRatio: 0.11,
    turnsPerActiveDay: 11,
    costUsdPer1k: 0.0012,
    costCnyPer1k: 0.0085,
    salt: 61,
    spikeDaysAgo: [28, 24],
    spikeMultiplier: 1.9
  },
  // Kimi K2.6 — recent complex-task model, a few heavy nights.
  {
    model: 'qingyun::kimi-k2.6',
    fromDaysAgo: 22,
    toDaysAgo: 0,
    activeRate: 0.42,
    inputPerActiveDay: 165_000,
    outputRatio: 0.038,
    turnsPerActiveDay: 3,
    costUsdPer1k: 0.0035,
    costCnyPer1k: 0.025,
    salt: 67,
    spikeDaysAgo: [1, 5, 14],
    spikeMultiplier: 3.1
  },
  // Kimi code — brand-new, tiny exploratory usage.
  {
    model: 'qingyun::kimi-k2.7-code',
    fromDaysAgo: 6,
    toDaysAgo: 0,
    activeRate: 0.28,
    inputPerActiveDay: 9_200,
    outputRatio: 0.14,
    turnsPerActiveDay: 2,
    costUsdPer1k: 0.0015,
    costCnyPer1k: 0.011,
    salt: 71
  },
  // MiniMax M2.7 — tried earlier, mostly forgotten.
  {
    model: 'qingyun::minimax-m2.7',
    fromDaysAgo: 48,
    toDaysAgo: 8,
    activeRate: 0.18,
    inputPerActiveDay: 22_000,
    outputRatio: 0.06,
    turnsPerActiveDay: 3,
    costUsdPer1k: 0.001,
    costCnyPer1k: 0.007,
    salt: 73
  },
  // MiniMax M3 — recent evaluation, moderate.
  {
    model: 'qingyun::minimax-m3',
    fromDaysAgo: 13,
    toDaysAgo: 0,
    activeRate: 0.45,
    inputPerActiveDay: 74_000,
    outputRatio: 0.05,
    turnsPerActiveDay: 4,
    costUsdPer1k: 0.0016,
    costCnyPer1k: 0.012,
    salt: 79,
    spikeDaysAgo: [3, 9],
    spikeMultiplier: 2.0
  },
  // Doubao 2.0 Code — agentic coding sprint (composer list).
  {
    model: 'qingyun::doubao-seed-2.0-code',
    fromDaysAgo: 24,
    toDaysAgo: 0,
    activeRate: 0.56,
    inputPerActiveDay: 132_000,
    outputRatio: 0.115,
    turnsPerActiveDay: 10,
    costUsdPer1k: 0.0014,
    costCnyPer1k: 0.01,
    salt: 83,
    spikeDaysAgo: [1, 5, 12, 19],
    spikeMultiplier: 2.5
  },
  // GPT-4o — early OpenAI period before leaning on DeepSeek.
  {
    model: 'qingyun::gpt-4o',
    fromDaysAgo: 82,
    toDaysAgo: 38,
    activeRate: 0.54,
    inputPerActiveDay: 48_000,
    outputRatio: 0.038,
    turnsPerActiveDay: 5,
    costUsdPer1k: 0.005,
    costCnyPer1k: 0.036,
    salt: 87,
    spikeDaysAgo: [72, 58, 45],
    spikeMultiplier: 2.6
  },
  // GPT-3.5-turbo — legacy quick pings, faded out.
  {
    model: 'qingyun::gpt-3.5-turbo',
    fromDaysAgo: 89,
    toDaysAgo: 55,
    activeRate: 0.24,
    inputPerActiveDay: 9_800,
    outputRatio: 0.075,
    turnsPerActiveDay: 5,
    costUsdPer1k: 0.0005,
    costCnyPer1k: 0.0035,
    salt: 91
  },
  // Claude 3.5 Sonnet — steady secondary for writing and review.
  {
    model: 'qingyun::claude-3-5-sonnet',
    fromDaysAgo: 68,
    toDaysAgo: 0,
    activeRate: 0.44,
    inputPerActiveDay: 68_000,
    outputRatio: 0.041,
    turnsPerActiveDay: 4,
    costUsdPer1k: 0.003,
    costCnyPer1k: 0.022,
    salt: 95,
    spikeDaysAgo: [6, 17, 33, 52],
    spikeMultiplier: 2.1
  },
  // Claude 3 Opus — rare deep-reasoning nights.
  {
    model: 'qingyun::claude-3-opus',
    fromDaysAgo: 56,
    toDaysAgo: 14,
    activeRate: 0.17,
    inputPerActiveDay: 192_000,
    outputRatio: 0.034,
    turnsPerActiveDay: 2,
    costUsdPer1k: 0.015,
    costCnyPer1k: 0.11,
    salt: 97,
    spikeDaysAgo: [42, 28, 19],
    spikeMultiplier: 3.0
  },
  // Gemini 1.5 Pro — short evaluation window.
  {
    model: 'qingyun::gemini-1.5-pro',
    fromDaysAgo: 40,
    toDaysAgo: 20,
    activeRate: 0.38,
    inputPerActiveDay: 92_000,
    outputRatio: 0.039,
    turnsPerActiveDay: 3,
    costUsdPer1k: 0.0035,
    costCnyPer1k: 0.025,
    salt: 101,
    spikeDaysAgo: [32, 24],
    spikeMultiplier: 2.2
  },
  // Llama 3 70B — recent open-weight experiment.
  {
    model: 'qingyun::llama-3-70b',
    fromDaysAgo: 19,
    toDaysAgo: 2,
    activeRate: 0.34,
    inputPerActiveDay: 38_000,
    outputRatio: 0.058,
    turnsPerActiveDay: 3,
    costUsdPer1k: 0.0009,
    costCnyPer1k: 0.0065,
    salt: 103,
    spikeDaysAgo: [8, 14],
    spikeMultiplier: 1.8
  }
]

/** Hand-picked days that tell a story (daysAgo → model → session). */
const HANDCRAFTED_SESSIONS: Array<{
  daysAgo: number
  model: string
  input: number
  output: number
  turns: number
  costUsdPer1k: number
  costCnyPer1k: number
}> = [
  // Today: big Kimi session last night + normal flash background already from arc.
  {
    daysAgo: 0,
    model: 'qingyun::kimi-k2.6',
    input: 412_000,
    output: 18_600,
    turns: 2,
    costUsdPer1k: 0.0035,
    costCnyPer1k: 0.025
  },
  // Yesterday: GLM 5.2 long context job.
  {
    daysAgo: 1,
    model: 'qingyun::glm-5.2',
    input: 680_000,
    output: 24_000,
    turns: 1,
    costUsdPer1k: 0.0022,
    costCnyPer1k: 0.016
  },
  // Quiet week — only a tiny flash ping.
  {
    daysAgo: 16,
    model: 'deepseek-v4-flash',
    input: 1_800,
    output: 120,
    turns: 1,
    costUsdPer1k: 0.00035,
    costCnyPer1k: 0.0025
  },
  // First day trying Kimi code — one small refactor.
  {
    daysAgo: 4,
    model: 'qingyun::kimi-k2.7-code',
    input: 28_400,
    output: 4_100,
    turns: 3,
    costUsdPer1k: 0.0015,
    costCnyPer1k: 0.011
  },
  // Old GLM 5.1 farewell week.
  {
    daysAgo: 32,
    model: 'qingyun::glm-5.1',
    input: 95_000,
    output: 3_200,
    turns: 2,
    costUsdPer1k: 0.0018,
    costCnyPer1k: 0.013
  },
  // Late March: GPT-4o before switching defaults to DeepSeek.
  {
    daysAgo: 78,
    model: 'qingyun::gpt-4o',
    input: 548_000,
    output: 21_400,
    turns: 4,
    costUsdPer1k: 0.005,
    costCnyPer1k: 0.036
  },
  // Early April: GPT-3.5 batch tagging job.
  {
    daysAgo: 68,
    model: 'qingyun::gpt-3.5-turbo',
    input: 124_000,
    output: 9_600,
    turns: 18,
    costUsdPer1k: 0.0005,
    costCnyPer1k: 0.0035
  },
  // Mid April: Claude Opus architecture review.
  {
    daysAgo: 52,
    model: 'qingyun::claude-3-opus',
    input: 920_000,
    output: 32_800,
    turns: 1,
    costUsdPer1k: 0.015,
    costCnyPer1k: 0.11
  },
  // May: Claude Sonnet documentation sprint.
  {
    daysAgo: 44,
    model: 'qingyun::claude-3-5-sonnet',
    input: 336_000,
    output: 14_100,
    turns: 5,
    costUsdPer1k: 0.003,
    costCnyPer1k: 0.022
  },
  // Late May: Gemini multimodal eval.
  {
    daysAgo: 28,
    model: 'qingyun::gemini-1.5-pro',
    input: 268_000,
    output: 10_500,
    turns: 3,
    costUsdPer1k: 0.0035,
    costCnyPer1k: 0.025
  },
  // This week: Doubao 2.0 Code agent refactor.
  {
    daysAgo: 2,
    model: 'qingyun::doubao-seed-2.0-code',
    input: 215_000,
    output: 27_800,
    turns: 7,
    costUsdPer1k: 0.0014,
    costCnyPer1k: 0.01
  },
  // Llama proxy smoke test.
  {
    daysAgo: 11,
    model: 'qingyun::llama-3-70b',
    input: 82_000,
    output: 5_900,
    turns: 2,
    costUsdPer1k: 0.0009,
    costCnyPer1k: 0.0065
  },
  // Weekend spike: v4-pro long agent run (fills recent chart).
  {
    daysAgo: 6,
    model: 'deepseek-v4-pro',
    input: 612_000,
    output: 19_400,
    turns: 3,
    costUsdPer1k: 0.002,
    costCnyPer1k: 0.014
  },
  // Doubao pro sprint peak (historical).
  {
    daysAgo: 47,
    model: 'qingyun::doubao-seed-2.0-pro',
    input: 485_000,
    output: 24_200,
    turns: 6,
    costUsdPer1k: 0.0025,
    costCnyPer1k: 0.018
  }
]

function localDayKey(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function seededUnit(seed: number): number {
  const value = Math.sin(seed * 12.9898) * 43758.5453
  return value - Math.floor(value)
}

function emptyDayTotals(): Omit<UsageLedgerBucket, 'model'> {
  return {
    input_tokens: 0,
    output_tokens: 0,
    total_tokens: 0,
    cost_usd: 0,
    cost_cny: 0,
    turns: 0
  }
}

function sumDayTotals(models: Record<string, UsageLedgerBucket>): Omit<UsageLedgerBucket, 'model'> {
  const totals = emptyDayTotals()
  for (const bucket of Object.values(models)) {
    totals.input_tokens += bucket.input_tokens
    totals.output_tokens += bucket.output_tokens
    totals.total_tokens += bucket.total_tokens
    totals.cost_usd += bucket.cost_usd
    totals.cost_cny += bucket.cost_cny
    totals.turns += bucket.turns
  }
  return totals
}

function makeBucket(
  model: string,
  input: number,
  output: number,
  turns: number,
  costUsdPer1k: number,
  costCnyPer1k: number
): UsageLedgerBucket {
  const inputTokens = Math.max(0, Math.round(input))
  const outputTokens = Math.max(0, Math.round(output))
  const totalTokens = inputTokens + outputTokens
  return {
    model,
    input_tokens: inputTokens,
    output_tokens: outputTokens,
    total_tokens: totalTokens,
    cost_usd: Number(((totalTokens / 1000) * costUsdPer1k).toFixed(4)),
    cost_cny: Number(((totalTokens / 1000) * costCnyPer1k).toFixed(4)),
    turns: Math.max(1, Math.round(turns))
  }
}

function mergeBucket(target: UsageLedgerBucket, source: UsageLedgerBucket): void {
  target.input_tokens += source.input_tokens
  target.output_tokens += source.output_tokens
  target.total_tokens += source.total_tokens
  target.cost_usd += source.cost_usd
  target.cost_cny += source.cost_cny
  target.turns += source.turns
}

function addBucket(
  models: Record<string, UsageLedgerBucket>,
  bucket: UsageLedgerBucket
): void {
  const existing = models[bucket.model]
  if (existing) {
    mergeBucket(existing, bucket)
    return
  }
  models[bucket.model] = { ...bucket }
}

export function mergeUsageLedgers(base: UsageLedgerV1, overlay: UsageLedgerV1): UsageLedgerV1 {
  const days: Record<string, UsageLedgerDay> = structuredClone(base.days)
  for (const [day, overlayDay] of Object.entries(overlay.days)) {
    const existing = days[day] ?? { models: {}, totals: emptyDayTotals() }
    const models = { ...existing.models }
    for (const [model, bucket] of Object.entries(overlayDay.models)) {
      const target = models[model] ?? {
        model,
        input_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
        cost_usd: 0,
        cost_cny: 0,
        turns: 0
      }
      mergeBucket(target, bucket)
      models[model] = target
    }
    days[day] = { models, totals: sumDayTotals(models) }
  }
  return {
    ...base,
    days,
    updatedAt: new Date().toISOString()
  }
}

function arcSessionForDay(arc: ModelUsageArc, daysAgo: number): UsageLedgerBucket | null {
  if (daysAgo < arc.toDaysAgo || daysAgo > arc.fromDaysAgo) return null

  const isSpike = arc.spikeDaysAgo?.includes(daysAgo) ?? false
  if (!isSpike && seededUnit(daysAgo * 997 + arc.salt) > arc.activeRate) return null

  let input = arc.inputPerActiveDay
  if (isSpike) {
    input *= arc.spikeMultiplier ?? 2
  } else {
    const jitter = 0.55 + seededUnit(daysAgo * 131 + arc.salt) * 0.9
    input = Math.round(input * jitter)
  }

  const output = Math.max(1, Math.round(input * arc.outputRatio))
  const turns = Math.max(1, Math.round(arc.turnsPerActiveDay * (isSpike ? 1.4 : 0.7 + seededUnit(daysAgo + arc.salt) * 0.6)))

  return makeBucket(arc.model, input, output, turns, arc.costUsdPer1k, arc.costCnyPer1k)
}

/** Realistic uneven usage across the user's composer models. */
export function buildMockUsageLedger(now = new Date()): UsageLedgerV1 {
  const days: Record<string, UsageLedgerDay> = {}
  const anchor = new Date(now)
  anchor.setHours(0, 0, 0, 0)

  for (let daysAgo = USAGE_RETENTION_DAYS - 1; daysAgo >= 0; daysAgo -= 1) {
    const date = new Date(anchor)
    date.setDate(date.getDate() - daysAgo)
    const dayKey = localDayKey(date)
    const models: Record<string, UsageLedgerBucket> = {}

    for (const arc of MODEL_ARCS) {
      const bucket = arcSessionForDay(arc, daysAgo)
      if (bucket) addBucket(models, bucket)
    }

    for (const session of HANDCRAFTED_SESSIONS) {
      if (session.daysAgo !== daysAgo) continue
      addBucket(
        models,
        makeBucket(
          session.model,
          session.input,
          session.output,
          session.turns,
          session.costUsdPer1k,
          session.costCnyPer1k
        )
      )
    }

    if (Object.keys(models).length === 0) continue
    days[dayKey] = { models, totals: sumDayTotals(models) }
  }

  return {
    schemaVersion: USAGE_LEDGER_SCHEMA_VERSION,
    updatedAt: now.toISOString(),
    retentionDays: USAGE_RETENTION_DAYS,
    processedTurnIds: { 'mock-preview': localDayKey(anchor) },
    days
  }
}

export function isUsageMockEnabled(env: NodeJS.ProcessEnv = process.env): boolean {
  if (env.DEEPSEEK_USAGE_MOCK === '0') return false
  return env.DEEPSEEK_USAGE_MOCK === '1'
}

import { describe, expect, it } from 'vitest'
import {
  emptyUsageLedger,
  pruneUsageProvider,
  queryUsageLedger,
  type UsageLedgerV1
} from './usage-ledger'
import { buildMockUsageLedger, mergeUsageLedgers } from './usage-ledger-mock'

describe('usage-ledger', () => {
  it('aggregates daily and model totals for a range', () => {
    const today = new Date()
    today.setHours(12, 0, 0, 0)
    const day = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
    const ledger: UsageLedgerV1 = {
      ...emptyUsageLedger(),
      days: {
        [day]: {
          models: {
            'deepseek-chat': {
              model: 'deepseek-chat',
              input_tokens: 100,
              output_tokens: 20,
              total_tokens: 120,
              cost_usd: 0.01,
              cost_cny: 0,
              turns: 1
            }
          },
          totals: {
            input_tokens: 100,
            output_tokens: 20,
            total_tokens: 120,
            cost_usd: 0.01,
            cost_cny: 0,
            turns: 1
          }
        }
      }
    }

    const result = queryUsageLedger(ledger, '7d', 'en')
    expect(result.summary?.totals.totalTokens).toBe(120)
    expect(result.daily.at(-1)?.totalTokens).toBe(120)
  })

  it('prunes provider-scoped model refs', () => {
    const ledger: UsageLedgerV1 = {
      ...emptyUsageLedger(),
      days: {
        '2026-06-24': {
          models: {
            'qingyun::claude-sonnet': {
              model: 'qingyun::claude-sonnet',
              input_tokens: 10,
              output_tokens: 2,
              total_tokens: 12,
              cost_usd: 0,
              cost_cny: 0,
              turns: 1
            },
            'deepseek-chat': {
              model: 'deepseek-chat',
              input_tokens: 5,
              output_tokens: 1,
              total_tokens: 6,
              cost_usd: 0,
              cost_cny: 0,
              turns: 1
            }
          },
          totals: {
            input_tokens: 15,
            output_tokens: 3,
            total_tokens: 18,
            cost_usd: 0,
            cost_cny: 0,
            turns: 2
          }
        }
      }
    }

    const next = pruneUsageProvider(ledger, 'qingyun')
    expect(next.days['2026-06-24'].models['qingyun::claude-sonnet']).toBeUndefined()
    expect(next.days['2026-06-24'].models['deepseek-chat']).toBeDefined()
  })

  it('builds mock ledger with uneven model usage arcs', () => {
    const ledger = buildMockUsageLedger(new Date('2026-06-24T12:00:00'))
    const result = queryUsageLedger(ledger, '90d', 'en')
    const buckets = result.summary!.buckets

    expect(result.summary).not.toBeNull()
    expect(buckets.length).toBeGreaterThanOrEqual(16)
    expect(buckets.some((b) => b.model === 'deepseek-v4-pro')).toBe(true)
    expect(buckets.some((b) => b.model === 'qingyun::glm-5.2')).toBe(true)
    expect(buckets.some((b) => b.model === 'qingyun::doubao-seed-2.0-lite')).toBe(true)
    expect(buckets.some((b) => b.model === 'qingyun::gpt-4o')).toBe(true)
    expect(buckets.some((b) => b.model === 'qingyun::claude-3-5-sonnet')).toBe(true)
    expect(buckets.some((b) => b.model === 'qingyun::doubao-seed-2.0-code')).toBe(true)

    const maxTokens = buckets[0]?.totalTokens ?? 0
    const minTokens = buckets[buckets.length - 1]?.totalTokens ?? 0
    expect(maxTokens / Math.max(minTokens, 1)).toBeGreaterThan(20)

    const activeDays = result.daily.filter((point) => point.totalTokens > 0).length
    expect(activeDays).toBeGreaterThan(30)
    expect(activeDays).toBeLessThan(90)
  })

  it('merges mock overlay onto an existing ledger', () => {
    const base = emptyUsageLedger()
    const overlay = buildMockUsageLedger(new Date('2026-06-24T12:00:00'))
    const merged = mergeUsageLedgers(base, overlay)
    const result = queryUsageLedger(merged, '7d', 'en')

    expect(result.summary?.totals.totalTokens).toBeGreaterThan(0)
  })
})

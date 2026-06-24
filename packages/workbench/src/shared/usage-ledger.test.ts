import { describe, expect, it } from 'vitest'
import {
  emptyUsageLedger,
  pruneUsageProvider,
  queryUsageLedger,
  type UsageLedgerV1
} from './usage-ledger'

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
      },
      lifetime: { models: {} }
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
      },
      lifetime: { models: {} }
    }

    const next = pruneUsageProvider(ledger, 'qingyun')
    expect(next.days['2026-06-24'].models['qingyun::claude-sonnet']).toBeUndefined()
    expect(next.days['2026-06-24'].models['deepseek-chat']).toBeDefined()
  })
})

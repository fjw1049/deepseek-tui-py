import { describe, expect, it } from 'vitest'
import {
  accumulateSessionModelUsage,
  pruneSessionModelUsageEndpointModel,
  pruneSessionModelUsageProvider,
  toModelUsageSummary
} from './session-model-usage'

describe('session-model-usage', () => {
  it('accumulates per-model buckets from turn usage', () => {
    const session = accumulateSessionModelUsage(
      {},
      {
        models: {
          'deepseek-chat': { input_tokens: 10, output_tokens: 2, turns: 1 },
          'qingyun::claude-sonnet-4-6': { input_tokens: 5, output_tokens: 1, turns: 1 }
        }
      },
      'deepseek-chat'
    )
    expect(session['deepseek-chat'].totalTokens).toBe(12)
    expect(session['qingyun::claude-sonnet-4-6'].totalTokens).toBe(6)
  })

  it('prunes only the removed provider', () => {
    const session = {
      'deepseek-chat': {
        model: 'deepseek-chat',
        inputTokens: 10,
        outputTokens: 2,
        totalTokens: 12,
        costUsd: 0,
        costCny: 0,
        turns: 1
      },
      'qingyun::claude-sonnet-4-6': {
        model: 'qingyun::claude-sonnet-4-6',
        inputTokens: 5,
        outputTokens: 1,
        totalTokens: 6,
        costUsd: 0,
        costCny: 0,
        turns: 1
      }
    }
    const next = pruneSessionModelUsageProvider(session, 'qingyun')
    expect(next['deepseek-chat']).toBeDefined()
    expect(next['qingyun::claude-sonnet-4-6']).toBeUndefined()
  })

  it('prunes a single endpoint model ref', () => {
    const session = accumulateSessionModelUsage(
      {},
      { input_tokens: 3, output_tokens: 1, turns: 1 },
      'qingyun::claude-sonnet-4-6'
    )
    const next = pruneSessionModelUsageEndpointModel(session, 'qingyun', 'claude-sonnet-4-6')
    expect(Object.keys(next)).toHaveLength(0)
  })

  it('builds summary sorted by total tokens', () => {
    const summary = toModelUsageSummary({
      small: {
        model: 'small',
        inputTokens: 1,
        outputTokens: 1,
        totalTokens: 2,
        costUsd: 0,
        costCny: 0,
        turns: 1
      },
      large: {
        model: 'large',
        inputTokens: 10,
        outputTokens: 5,
        totalTokens: 15,
        costUsd: 0,
        costCny: 0,
        turns: 1
      }
    })
    expect(summary?.buckets.map((bucket) => bucket.model)).toEqual(['large', 'small'])
  })
})

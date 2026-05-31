import { describe, expect, it } from 'vitest'
import type { ChatBlock } from '../agent/types'
import {
  ENGINE_SYSTEM_BASELINE_TOKENS,
  ENGINE_TOOLS_BASELINE_TOKENS,
  contextBucketTokens,
  estimateContextUsageFallback,
  fallbackContextBreakdown,
  formatBucketPercent,
  formatTokenCount,
  snapshotFromContextBreakdown
} from './estimate-context-usage'

describe('snapshotFromContextBreakdown', () => {
  it('maps runtime breakdown like TUI /context', () => {
    const usage = snapshotFromContextBreakdown({
      system_prompt: 603,
      tools: 7800,
      conversation: 10700,
      total: 19103,
      window: 128000,
      free: 108897
    })
    expect(usage.usedTokens).toBe(19103)
    expect(usage.maxTokens).toBe(128000)
    expect(Math.round(usage.percent)).toBe(15)
  })
})

describe('estimateContextUsageFallback', () => {
  it('includes engine baseline on an empty transcript', () => {
    const usage = estimateContextUsageFallback([], 'deepseek-chat')
    expect(usage.usedTokens).toBe(
      ENGINE_SYSTEM_BASELINE_TOKENS + ENGINE_TOOLS_BASELINE_TOKENS
    )
  })

  it('adds conversation tokens', () => {
    const blocks: ChatBlock[] = [{ kind: 'user', id: 'u1', text: 'hello world' }]
    const usage = estimateContextUsageFallback(blocks, 'deepseek-chat')
    const baseline = ENGINE_SYSTEM_BASELINE_TOKENS + ENGINE_TOOLS_BASELINE_TOKENS
    expect(usage.usedTokens).toBe(baseline + Math.ceil('hello world'.length / 3) + 60)
  })
})

describe('formatTokenCount', () => {
  it('uses one decimal for kilo values like TUI', () => {
    expect(formatTokenCount(8400)).toBe('8.4k')
    expect(formatTokenCount(33400)).toBe('33.4k')
  })
})

describe('fallbackContextBreakdown', () => {
  it('fills free space from window minus total', () => {
    const b = fallbackContextBreakdown([], 'deepseek-chat')
    expect(b.free).toBe(b.window - b.total)
  })

  it('separates built-in tool definitions from MCP in the fallback shape', () => {
    const b = fallbackContextBreakdown([], 'deepseek-chat')
    expect(b.tool_definitions).toBe(ENGINE_TOOLS_BASELINE_TOKENS)
    expect(b.mcp).toBe(0)
    expect(b.skills).toBe(0)
    expect(b.rules).toBe(0)
  })
})

describe('formatBucketPercent', () => {
  it('matches TUI percent column width', () => {
    expect(formatBucketPercent(603, 128000)).toBe('  0.5%')
  })
})

describe('contextBucketTokens', () => {
  it('uses explicit tool_definitions when present', () => {
    expect(
      contextBucketTokens({
        system_prompt: 10,
        tool_definitions: 20,
        tools: 25,
        mcp: 5,
        skills: 3,
        rules: 2,
        conversation: 30,
        total: 70,
        window: 100,
        free: 30
      }, 'tool_definitions')
    ).toBe(20)
  })

  it('falls back to legacy tools when tool_definitions is absent', () => {
    expect(
      contextBucketTokens({
        system_prompt: 10,
        tools: 25,
        conversation: 30,
        total: 65,
        window: 100,
        free: 35
      }, 'tool_definitions')
    ).toBe(25)
  })
})

import { describe, expect, it } from 'vitest'

import {
  applyMailboxMessage,
  createDelegateCard,
  fanoutAggregateStatus,
  finalizeOrphanSubagentBlocks,
  type MailboxMessageJson
} from './subagent-mailbox'
import type { ChatBlock } from '../agent/types'

describe('subagent-mailbox', () => {
  it('creates delegate card on started and tracks actions', () => {
    const started: MailboxMessageJson = {
      kind: 'started',
      agent_id: 'agent_1',
      agent_type: 'general'
    }
    let cards = applyMailboxMessage({}, started)
    expect(cards.agent_1?.cardKind).toBe('delegate')

    const progress: MailboxMessageJson = {
      kind: 'progress',
      agent_id: 'agent_1',
      status: 'planning'
    }
    cards = applyMailboxMessage(cards, progress)
    const card = cards.agent_1
    expect(card?.cardKind).toBe('delegate')
    if (card?.cardKind === 'delegate') {
      expect(card.actions).toContain('planning')
      expect(card.status).toBe('running')
    }
  })

  it('bootstraps a delegate card when the first message is not started', () => {
    // Mid-stream join (SSE reconnect past the `started` seq): the first message
    // the UI sees is a tool call, which must still surface a card.
    const toolStart: MailboxMessageJson = {
      kind: 'tool_call_started',
      agent_id: 'agent_late',
      tool_name: 'read_file',
      step: 2
    }
    let cards = applyMailboxMessage({}, toolStart)
    const card = cards.agent_late
    expect(card?.cardKind).toBe('delegate')
    if (card?.cardKind === 'delegate') {
      expect(card.status).toBe('running')
      expect(card.actions.some((a) => a.includes('read_file'))).toBe(true)
    }

    const done: MailboxMessageJson = {
      kind: 'completed',
      agent_id: 'agent_late',
      summary: 'done'
    }
    cards = applyMailboxMessage(cards, done)
    const finished = cards.agent_late
    if (finished?.cardKind === 'delegate') {
      expect(finished.status).toBe('completed')
      expect(finished.summary).toBe('done')
    }
  })

  it('routes worker progress to the owning fanout instead of a stray card', () => {
    const cards = applyMailboxMessage(
      {
        fanout_1: {
          cardKind: 'fanout',
          agentId: 'fanout_1',
          dispatchKind: 'rlm',
          workers: [{ id: 'w1', status: 'pending' }]
        }
      },
      { kind: 'tool_call_started', agent_id: 'w1', tool_name: 'grep', step: 1 }
    )
    // No standalone delegate for the worker…
    expect(cards.w1).toBeUndefined()
    // …and the fanout marks it running.
    const card = cards.fanout_1
    if (card?.cardKind === 'fanout') {
      expect(card.workers.find((w) => w.id === 'w1')?.status).toBe('running')
    }
  })

  it('creates fanout card for rlm agent type', () => {
    const started: MailboxMessageJson = {
      kind: 'started',
      agent_id: 'swarm_root',
      agent_type: 'rlm'
    }
    const cards = applyMailboxMessage({}, started)
    expect(cards.swarm_root?.cardKind).toBe('fanout')
  })

  it('aggregates fanout worker lifecycle', () => {
    const root = createDelegateCard('x', 'y')
    void root
    const cards = applyMailboxMessage(
      {
        fanout_1: {
          cardKind: 'fanout',
          agentId: 'fanout_1',
          dispatchKind: 'rlm',
          workers: [
            { id: 'w1', status: 'completed' },
            { id: 'w2', status: 'running' }
          ]
        }
      },
      { kind: 'progress', agent_id: 'w2', status: 'working' }
    )
    const card = cards.fanout_1
    expect(card?.cardKind).toBe('fanout')
    if (card?.cardKind === 'fanout') {
      expect(fanoutAggregateStatus(card)).toBe('running')
    }
  })

  it('finalizes orphan running sub-agents when the turn is idle', () => {
    const blocks: ChatBlock[] = [
      {
        kind: 'subagent',
        id: 'subagent-fanout_1',
        cardKind: 'fanout',
        agentId: 'fanout_1',
        agentType: 'rlm',
        status: 'running',
        workers: [
          { id: 'w1', status: 'completed' },
          { id: 'w2', status: 'running' }
        ]
      },
      {
        kind: 'subagent',
        id: 'subagent-agent_1',
        cardKind: 'delegate',
        agentId: 'agent_1',
        agentType: 'general',
        status: 'running'
      }
    ]
    const next = finalizeOrphanSubagentBlocks(blocks)
    expect(next[0]).toMatchObject({
      kind: 'subagent',
      status: 'cancelled',
      workers: [
        { id: 'w1', status: 'completed' },
        { id: 'w2', status: 'cancelled' }
      ]
    })
    expect(next[1]).toMatchObject({ kind: 'subagent', status: 'cancelled' })
  })
})

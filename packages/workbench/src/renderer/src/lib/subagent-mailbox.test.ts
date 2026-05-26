import { describe, expect, it } from 'vitest'

import {
  applyMailboxMessage,
  createDelegateCard,
  fanoutAggregateStatus,
  type MailboxMessageJson
} from './subagent-mailbox'

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
})

import { describe, expect, it } from 'vitest'

import {
  applyMailboxMessage,
  applyMailboxMessageTouched,
  createDelegateCard,
  createFanoutCard,
  fanoutAggregateStatus,
  finalizeOrphanSubagentBlocks,
  subagentBlockFromCard,
  subagentCardsFromBlocks,
  subagentStepsToFlowItems,
  type MailboxMessageJson,
  type SubagentStepState
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
      expect(card.steps.some((s) => s.label === 'planning')).toBe(true)
    }
  })

  it('keeps full tool steps with I/O and links nested children', () => {
    let cards = applyMailboxMessage(
      {},
      { kind: 'started', agent_id: 'parent', agent_type: 'general' }
    )
    cards = applyMailboxMessage(cards, {
      kind: 'tool_call_started',
      agent_id: 'parent',
      tool_name: 'read_file',
      step: 1,
      input_summary: '{"path":"a.py"}'
    })
    cards = applyMailboxMessage(cards, {
      kind: 'tool_call_completed',
      agent_id: 'parent',
      tool_name: 'read_file',
      step: 1,
      ok: true,
      output_summary: 'print(1)'
    })
    cards = applyMailboxMessage(cards, {
      kind: 'child_spawned',
      agent_id: 'child',
      parent_id: 'parent',
      agent_type: 'explore'
    })

    const parent = cards.parent
    expect(parent?.cardKind).toBe('delegate')
    if (parent?.cardKind === 'delegate') {
      expect(parent.childIds).toContain('child')
      const tool = parent.steps.find((s) => s.kind === 'tool')
      expect(tool?.label).toContain('read_file')
      expect(tool?.input).toContain('a.py')
      expect(tool?.output).toContain('print(1)')
      expect(tool?.ok).toBe(true)
    }
    const child = cards.child
    expect(child?.cardKind).toBe('delegate')
    if (child?.cardKind === 'delegate') {
      expect(child.parentId).toBe('parent')
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
    const root = createFanoutCard('fanout_1', 'rlm')
    root.workers = [{ id: 'w1', status: 'pending' }]
    const cards = applyMailboxMessage(
      { fanout_1: root },
      { kind: 'tool_call_started', agent_id: 'w1', tool_name: 'grep', step: 1 }
    )
    // No standalone delegate for the worker…
    expect(cards.w1).toBeUndefined()
    // …and the fanout marks it running.
    const card = cards.fanout_1
    if (card?.cardKind === 'fanout') {
      expect(card.workers.find((w) => w.id === 'w1')?.status).toBe('running')
      expect(card.workerSteps.w1?.some((s) => s.toolName === 'grep')).toBe(true)
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
    void createDelegateCard('x', 'y')
    const root = createFanoutCard('fanout_1', 'rlm')
    root.workers = [
      { id: 'w1', status: 'completed' },
      { id: 'w2', status: 'running' }
    ]
    const cards = applyMailboxMessage(
      { fanout_1: root },
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

  it('keeps parallel same-name tool calls distinct via tool_call_id', () => {
    let cards = applyMailboxMessage(
      {},
      { kind: 'started', agent_id: 'agent_1', agent_type: 'general', seq: 1 }
    )
    // Same round (step 2), same tool name, two parallel calls.
    cards = applyMailboxMessage(cards, {
      kind: 'tool_call_started',
      agent_id: 'agent_1',
      tool_name: 'read_file',
      step: 2,
      tool_call_id: 'call_a',
      seq: 2,
      input_summary: '{"path":"a.py"}'
    })
    cards = applyMailboxMessage(cards, {
      kind: 'tool_call_started',
      agent_id: 'agent_1',
      tool_name: 'read_file',
      step: 2,
      tool_call_id: 'call_b',
      seq: 3,
      input_summary: '{"path":"b.py"}'
    })
    let card = cards.agent_1
    if (card?.cardKind === 'delegate') {
      const tools = card.steps.filter((s) => s.kind === 'tool')
      expect(tools).toHaveLength(2)
      expect(new Set(tools.map((s) => s.id)).size).toBe(2)
    }

    // Completing one call must not clobber the other.
    cards = applyMailboxMessage(cards, {
      kind: 'tool_call_completed',
      agent_id: 'agent_1',
      tool_name: 'read_file',
      step: 2,
      tool_call_id: 'call_b',
      ok: true,
      seq: 4,
      output_summary: 'b contents'
    })
    card = cards.agent_1
    if (card?.cardKind === 'delegate') {
      const a = card.steps.find((s) => s.id === 'tool-call_a')
      const b = card.steps.find((s) => s.id === 'tool-call_b')
      expect(a?.ok).toBeNull()
      expect(b?.ok).toBe(true)
      expect(b?.output).toContain('b contents')
    }
  })

  it('keeps step ids unique after the 200-step cap', () => {
    let cards = applyMailboxMessage(
      {},
      { kind: 'started', agent_id: 'agent_1', agent_type: 'general', seq: 1 }
    )
    for (let i = 2; i <= 230; i += 1) {
      cards = applyMailboxMessage(cards, {
        kind: 'progress',
        agent_id: 'agent_1',
        status: `p${i}`,
        seq: i
      })
    }
    const card = cards.agent_1
    expect(card?.cardKind).toBe('delegate')
    if (card?.cardKind === 'delegate') {
      expect(card.steps).toHaveLength(200)
      const ids = card.steps.map((s) => s.id)
      expect(new Set(ids).size).toBe(ids.length)
    }
  })

  it('falls back to unique lifecycle ids when seq is absent', () => {
    let cards = applyMailboxMessage(
      {},
      { kind: 'started', agent_id: 'agent_1', agent_type: 'general' }
    )
    cards = applyMailboxMessage(cards, {
      kind: 'progress',
      agent_id: 'agent_1',
      status: 'one'
    })
    cards = applyMailboxMessage(cards, {
      kind: 'progress',
      agent_id: 'agent_1',
      status: 'two'
    })
    const card = cards.agent_1
    if (card?.cardKind === 'delegate') {
      const ids = card.steps.map((s) => s.id)
      expect(new Set(ids).size).toBe(ids.length)
    }
  })

  it('keeps parent childIds through the live rebuild-from-blocks cycle', () => {
    // Mirror the chat-store live path: rebuild the card map from blocks on
    // every event and write back only the touched cards.
    const applyToBlocks = (
      blocks: ChatBlock[],
      msg: MailboxMessageJson
    ): { blocks: ChatBlock[]; touched: string[] } => {
      const applied = applyMailboxMessageTouched(subagentCardsFromBlocks(blocks), msg)
      let next = blocks
      for (const agentId of applied.touched) {
        const card = applied.cards[agentId]
        if (!card) continue
        const block = subagentBlockFromCard(card)
        const idx = next.findIndex((b) => b.id === block.id)
        next = idx >= 0 ? next.map((b, i) => (i === idx ? block : b)) : [...next, block]
      }
      return { blocks: next, touched: applied.touched }
    }

    let blocks: ChatBlock[] = []
    blocks = applyToBlocks(blocks, {
      kind: 'started',
      agent_id: 'parent',
      agent_type: 'general',
      seq: 1
    }).blocks
    const spawned = applyToBlocks(blocks, {
      kind: 'child_spawned',
      agent_id: 'child',
      parent_id: 'parent',
      agent_type: 'explore',
      seq: 2
    })
    // child_spawned rewrites the parent card too — both must be written back.
    expect(spawned.touched).toEqual(expect.arrayContaining(['parent', 'child']))
    blocks = spawned.blocks

    const progressed = applyToBlocks(blocks, {
      kind: 'tool_call_completed',
      agent_id: 'parent',
      tool_name: 'grep',
      step: 2,
      tool_call_id: 'call_1',
      ok: true,
      seq: 3
    })
    // Unrelated cards are not rewritten by a single-agent event.
    expect(progressed.touched).toEqual(['parent'])
    blocks = progressed.blocks

    const parentBlock = blocks.find((b) => b.kind === 'subagent' && b.agentId === 'parent')
    expect(parentBlock).toMatchObject({ childIds: expect.arrayContaining(['child']) })
    const childBlock = blocks.find((b) => b.kind === 'subagent' && b.agentId === 'child')
    expect(childBlock).toMatchObject({ parentId: 'parent' })
  })

  it('degrades residual running steps once the card is terminal', () => {
    const steps: SubagentStepState[] = [
      { id: 'started-1', kind: 'started', label: '● running' },
      {
        id: 'tool-call_a',
        kind: 'tool',
        step: 2,
        toolName: 'read_file',
        ok: null,
        label: 'step 2 · read_file'
      },
      {
        id: 'tool-call_b',
        kind: 'tool',
        step: 2,
        toolName: 'grep',
        ok: true,
        label: 'step 2 · grep · ok'
      }
    ]
    const failed = subagentStepsToFlowItems(steps, 0, 'failed')
    expect(failed.find((i) => i.id === 'tool-call_a')?.status).toBe('cancelled')
    expect(failed.find((i) => i.id === 'started-1')?.status).toBe('cancelled')
    expect(failed.find((i) => i.id === 'tool-call_b')?.status).toBe('ok')

    const interrupted = subagentStepsToFlowItems(steps, 0, 'interrupted')
    expect(interrupted.find((i) => i.id === 'tool-call_a')?.status).toBe('cancelled')

    const completed = subagentStepsToFlowItems(steps, 0, 'completed')
    expect(completed.find((i) => i.id === 'tool-call_a')?.status).toBe('info')
    expect(completed.find((i) => i.id === 'tool-call_b')?.status).toBe('ok')

    // Live cards keep pulsing; the param is optional and backward compatible.
    const live = subagentStepsToFlowItems(steps)
    expect(live.find((i) => i.id === 'tool-call_a')?.status).toBe('running')
    const running = subagentStepsToFlowItems(steps, 0, 'running')
    expect(running.find((i) => i.id === 'tool-call_a')?.status).toBe('running')
  })
})

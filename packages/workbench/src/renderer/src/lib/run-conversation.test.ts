import { expect, it } from 'vitest'
import { legacyRunConversation } from './run-conversation'

it('keeps same-name calls distinct and preserves legacy non-JSON previews', () => {
  const { blocks } = legacyRunConversation({ id: 'a', active: false, prompt: 'Work', steps: [
    { id: 'call1', kind: 'tool', toolName: 'read_file', input: '{clipped', output: 'one', ok: true, label: 'read' },
    { id: 'call2', kind: 'tool', toolName: 'read_file', input: '{"path":"b"}', output: 'two', ok: false, label: 'read' }
  ], result: 'Done' })
  expect(new Set(blocks.map((block) => block.id)).size).toBe(blocks.length)
  expect(blocks[1]).toMatchObject({ status: 'success', detail: 'one' })
  expect(blocks[2]).toMatchObject({ status: 'error', meta: { tool_input: { path: 'b' } } })
  expect(blocks.at(-1)).toMatchObject({ text: 'Done', agentSegment: 'final_answer' })
})
it('does not repeat settled narration in accumulated live text or a final report', () => {
  const steps = [{ id: 'progress1', kind: 'progress' as const, label: 'Inspect files' }]
  const live = legacyRunConversation({ id: 'a', active: true, steps, live: 'Inspect filesNew text' })
  expect(live.blocks.at(-1)).toMatchObject({ text: 'New text' })
  const final = legacyRunConversation({ id: 'a', active: false, steps, result: 'Inspect files' })
  expect(final.blocks).toHaveLength(1)
  expect(final.blocks[0]).toMatchObject({ agentSegment: 'final_answer' })
})

import { expect, it } from 'vitest'
import { resolveTurnActivity, resolveTurnActivityStep } from './TurnActivity'
import type { ChatBlock } from '../../agent/types'

it('uses event states for waiting, model, tools and human gates, never history text', () => {
  const browser: ChatBlock = { kind: 'tool', id: 'browser', toolKind: 'tool_call', status: 'running',
    summary: 'browser', meta: { tool_name: 'browser_use' } }
  const base = { active: true, blocks: [] as ChatBlock[], stream: null }
  expect(resolveTurnActivity(base)).toBe('Waiting')
  expect(resolveTurnActivity({ ...base, stream: 'thinking' })).toBe('Thinking')
  expect(resolveTurnActivity({ ...base, stream: 'responding' })).toBe('Responding')
  expect(resolveTurnActivity({ ...base, blocks: [browser] })).toBe('Browser')
  expect(resolveTurnActivity({ ...base, blocks: [{ ...browser, meta: { tool_name: 'cua_js' } }] })).toBe('Desktop')
  expect(resolveTurnActivity({ ...base, blocks: [{ ...browser, meta: { tool_name: 'read_file' } }] })).toBe('Tool')
  expect(resolveTurnActivity({ ...base, blocks: [{ ...browser, status: 'success' }] })).toBe('Waiting')
  expect(resolveTurnActivity({ ...base, blocks: [{ kind: 'reasoning', id: 'old', text: 'old' }] })).toBe('Waiting')
  expect(resolveTurnActivity({ ...base, stream: 'thinking', awaitingBrowserUser: true })).toBe('User')
  const question: ChatBlock = { kind: 'user_input', id: 'ask', requestId: 'r', questions: [], status: 'pending' }
  expect(resolveTurnActivity({ ...base, blocks: [question] })).toBe('User')
  expect(resolveTurnActivity({ ...base, blocks: [{ ...question, status: 'submitted' }] })).toBe('Waiting')
  expect(resolveTurnActivity({ ...base, active: false, awaitingBrowserUser: true, stream: 'thinking' })).toBeNull()
})

it('shows the current subagent handoff without reusing an old wait status', () => {
  const waiting: ChatBlock = { kind: 'system', id: 'wait', text: 'Waiting on 1 sub-agent(s) to complete...' }
  const base = { active: true, blocks: [waiting], stream: null }
  expect(resolveTurnActivity(base)).toBe('Subagent')
  expect(resolveTurnActivity({ ...base, stream: 'responding' })).toBe('Responding')
  expect(resolveTurnActivity({ ...base, active: false })).toBeNull()
  expect(resolveTurnActivity({ ...base, blocks: [waiting,
    { kind: 'system', id: 'resume', text: 'Resuming turn with 1 sub-agent completion(s)' }] })).toBe('Waiting')
})

it('names the running desktop step by the call\'s own title', () => {
  const call = (status: 'running' | 'success', title: string, tool = 'cua_js'): ChatBlock => ({
    kind: 'tool', id: 'cua', toolKind: 'tool_call', status, summary: tool,
    meta: { tool_name: tool, tool_input: { code: 'await app.click(75)', title } }
  })
  expect(resolveTurnActivityStep([call('running', '进入电视剧频道')])).toBe('进入电视剧频道')
  expect(resolveTurnActivityStep([call('success', '进入电视剧频道')])).toBeNull()
  expect(resolveTurnActivityStep([call('running', '读取文件', 'read_file')])).toBeNull()
  expect(resolveTurnActivityStep([call('running', '  ')])).toBeNull()
})

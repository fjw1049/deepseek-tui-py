// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from 'vitest'
import { MAX_CHAT_PANES, sanitizeChatLayout, useChatLayoutStore } from './chat-layout-store'

beforeEach(() => {
  const values = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', { configurable: true, value: {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value), clear: () => values.clear()
  } })
  useChatLayoutStore.setState({ layouts: {}, activeLayoutKey: null })
})

describe('project conversation splits', () => {
  it('rejects the seventh pane through every add direction and still permits replacement', () => {
    const actions = useChatLayoutStore.getState()
    expect(actions.add('/repo', 'a', 'b')).toBe(true)
    expect(actions.add('/repo', 'a', 'c', 'left')).toBe(true)
    expect(actions.add('/repo', 'a', 'd')).toBe(true)
    expect(actions.add('/repo', 'a', 'e', 'left')).toBe(true)
    expect(actions.add('/repo', 'a', 'f')).toBe(true)
    for (let i = 0; i < 20; i++) expect(actions.add('/repo', 'a', `extra-${i}`, i % 2 ? 'left' : 'right')).toBe(false)
    let layout = useChatLayoutStore.getState().layouts['/repo']
    expect(layout.panes).toHaveLength(MAX_CHAT_PANES)
    expect(sanitizeChatLayout(JSON.parse(window.localStorage.getItem('deepseek.chat-layouts.v1')!)['/repo'])?.panes).toEqual(layout.panes)
    actions.bind('/repo', layout.focused, 'replacement')
    layout = useChatLayoutStore.getState().layouts['/repo']
    expect(layout.panes).toHaveLength(6)
    expect(layout.panes.find(p => p.id === layout.focused)?.threadId).toBe('replacement')
  })

  it('focuses an already visible task without duplicating it or overwriting the other pane', () => {
    const actions = useChatLayoutStore.getState()
    actions.add('/repo', 'a', 'b')
    const before = useChatLayoutStore.getState().layouts['/repo']
    actions.bind('/repo', before.focused, 'a')
    const after = useChatLayoutStore.getState().layouts['/repo']
    expect(after.panes).toEqual(before.panes)
    expect(after.panes.find(p => p.id === after.focused)?.threadId).toBe('a')
  })

  it('closes the selected pane, restores the survivor, and keeps projects independent', () => {
    const actions = useChatLayoutStore.getState()
    actions.add('/repo', 'a', 'b')
    actions.add('/other', 'c', 'd')
    actions.resize('/repo', 'x', .65)
    actions.close('/repo', useChatLayoutStore.getState().layouts['/repo'].focused)
    const { layouts } = useChatLayoutStore.getState()
    expect(layouts['/repo'].panes.map(p => p.threadId)).toEqual(['a'])
    expect(layouts['/repo'].focused).toBe(layouts['/repo'].panes[0].id)
    expect(layouts['/other'].panes.map(p => p.threadId)).toEqual(['c', 'd'])
    expect(JSON.parse(window.localStorage.getItem('deepseek.chat-layouts.v1')!)).toEqual(layouts)
  })

  it('clears removed/archived tasks and sanitizes corrupt or oversized persisted layouts', () => {
    const raw = { panes: Array.from({ length: 8 }, (_, i) => ({ id: `${i}`, threadId: `t${i}` })), focused: 'missing', x: 100, y: 'bad' }
    const clean = sanitizeChatLayout(raw)!
    expect(clean.panes).toHaveLength(6)
    expect(clean).toMatchObject({ focused: '0', x: .75, y: .5 })
    expect(sanitizeChatLayout({ panes: [null, {}, { id: 'a', threadId: 5 }] })).toBeNull()
    useChatLayoutStore.setState({ layouts: { '/repo': clean } })
    useChatLayoutStore.getState().reconcile('/repo', ['t0'])
    expect(useChatLayoutStore.getState().layouts['/repo'].panes.map(p => p.threadId)).toEqual(['t0', null, null, null, null, null])
  })
})


it('persists arrangement and restores old or invalid layouts as a grid', () => {
  const actions = useChatLayoutStore.getState()
  actions.add('/repo', 'a', 'b')
  actions.arrange('/repo', 'vertical')
  const layout = useChatLayoutStore.getState().layouts['/repo']
  expect(layout.arrangement).toBe('vertical')
  expect(JSON.parse(window.localStorage.getItem('deepseek.chat-layouts.v1')!)['/repo'].arrangement).toBe('vertical')
  expect(sanitizeChatLayout({ ...layout, arrangement: undefined })?.arrangement).toBe('grid')
  expect(sanitizeChatLayout({ ...layout, arrangement: 'invalid' })?.arrangement).toBe('grid')
})

it('swaps pane identities, focuses the dragged conversation, and persists the new order', () => {
  const actions = useChatLayoutStore.getState()
  actions.add('/repo', 'a', 'b')
  actions.add('/repo', 'a')
  const before = useChatLayoutStore.getState().layouts['/repo'].panes
  expect(actions.drop('/repo', before[1].id, 'a')).toBe(true)
  let layout = useChatLayoutStore.getState().layouts['/repo']
  expect(layout.panes).toEqual([before[1], before[0], before[2]])
  expect(layout.focused).toBe(before[0].id)
  expect(actions.drop('/repo', before[2].id, 'a')).toBe(true)
  layout = useChatLayoutStore.getState().layouts['/repo']
  expect(layout.panes).toEqual([before[1], before[2], before[0]])
  expect(JSON.parse(window.localStorage.getItem('deepseek.chat-layouts.v1')!)['/repo']).toEqual(layout)
  expect(actions.drop('/repo', 'missing-pane', 'a')).toBe(false)
  expect(useChatLayoutStore.getState().layouts['/repo']).toBe(layout)
})

it('replaces only the requested pane at capacity, and treats dropping onto itself as a no-op', () => {
  const actions = useChatLayoutStore.getState()
  for (const id of ['b', 'c', 'd', 'e', 'f']) actions.add('/repo', 'a', id)
  const before = useChatLayoutStore.getState().layouts['/repo'].panes
  expect(actions.drop('/repo', before[2].id, 'new')).toBe(true)
  const layout = useChatLayoutStore.getState().layouts['/repo']
  expect(layout.panes.map(p => p.threadId)).toEqual(['a', 'b', 'new', 'd', 'e', 'f'])
  expect(layout.focused).toBe(before[2].id)
  expect(actions.drop('/repo', before[2].id, 'new')).toBe(true)
  expect(useChatLayoutStore.getState().layouts['/repo'].panes).toEqual(layout.panes)
})

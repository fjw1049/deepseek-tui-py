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
  it('rejects the fifth pane through every add direction and still permits replacement', () => {
    const actions = useChatLayoutStore.getState()
    expect(actions.add('/repo', 'a', 'b')).toBe(true)
    expect(actions.add('/repo', 'a', 'c', 'left')).toBe(true)
    expect(actions.add('/repo', 'a', 'd')).toBe(true)
    for (let i = 0; i < 20; i++) expect(actions.add('/repo', 'a', `extra-${i}`, i % 2 ? 'left' : 'right')).toBe(false)
    let layout = useChatLayoutStore.getState().layouts['/repo']
    expect(layout.panes).toHaveLength(MAX_CHAT_PANES)
    actions.bind('/repo', layout.focused, 'replacement')
    layout = useChatLayoutStore.getState().layouts['/repo']
    expect(layout.panes).toHaveLength(4)
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
    expect(clean.panes).toHaveLength(4)
    expect(clean).toMatchObject({ focused: '0', x: .75, y: .5 })
    expect(sanitizeChatLayout({ panes: [null, {}, { id: 'a', threadId: 5 }] })).toBeNull()
    useChatLayoutStore.setState({ layouts: { '/repo': clean } })
    useChatLayoutStore.getState().reconcile('/repo', ['t0'])
    expect(useChatLayoutStore.getState().layouts['/repo'].panes.map(p => p.threadId)).toEqual(['t0', null, null, null])
  })
})

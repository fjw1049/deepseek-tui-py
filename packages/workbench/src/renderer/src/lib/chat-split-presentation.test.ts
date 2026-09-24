import { expect, it } from 'vitest'
import { resolveChatSplitPresentation } from './chat-split-presentation'

it('keeps the requested arrangement when it fits and uses a grid before hiding panes', () => {
  expect(resolveChatSplitPresentation(3, 'horizontal', 1280, 900)).toBe('horizontal')
  expect(resolveChatSplitPresentation(4, 'horizontal', 1280, 900)).toBe('grid')
  expect(resolveChatSplitPresentation(4, 'vertical', 1280, 900)).toBe('grid')
  expect(resolveChatSplitPresentation(6, 'horizontal', 1280, 900)).toBe('grid')
  expect(resolveChatSplitPresentation(4, 'horizontal', 1600, 900)).toBe('horizontal')
})

it('uses tabs only when neither layout fits and never hides a single pane', () => {
  expect(resolveChatSplitPresentation(4, 'grid', 600, 900)).toBe('tabs')
  expect(resolveChatSplitPresentation(4, 'grid', 1280, 500)).toBe('tabs')
  expect(resolveChatSplitPresentation(1, 'grid', 320, 200)).toBe('grid')
})

it('keeps explicitly selected tabs in a large window but restores a single pane with one task', () => {
  expect(resolveChatSplitPresentation(4, 'tabs', 2400, 1400)).toBe('tabs')
  expect(resolveChatSplitPresentation(1, 'tabs', 2400, 1400)).toBe('grid')
  expect(resolveChatSplitPresentation(1, 'tabs', 320, 200)).toBe('grid')
  expect(resolveChatSplitPresentation(1, 'tabs', 0, 0)).toBe('grid')
})

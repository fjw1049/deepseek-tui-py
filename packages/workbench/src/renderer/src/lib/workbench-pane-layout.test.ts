import { expect, it } from 'vitest'
import { resolveRightPanelLayout } from './workbench-pane-layout'

it('protects a readable chat column when a large right panel is requested', () => {
  expect(resolveRightPanelLayout(900, 700)).toEqual({ rightWidth: 500, chatHidden: false })
})
it('preserves a requested split when both panels fit', () => {
  expect(resolveRightPanelLayout(900, 300)).toEqual({ rightWidth: 300, chatHidden: false })
})
it('shows a single panel when two usable columns cannot fit', () => {
  expect(resolveRightPanelLayout(600, 260)).toEqual({ rightWidth: 600, chatHidden: true })
  expect(resolveRightPanelLayout(660, 260)).toEqual({ rightWidth: 260, chatHidden: false })
})
it('still permits an explicit maximize gesture', () => {
  expect(resolveRightPanelLayout(900, 875)).toEqual({ rightWidth: 900, chatHidden: true })
})

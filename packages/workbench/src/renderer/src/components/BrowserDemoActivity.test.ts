import { describe, expect, it } from 'vitest'
import { describeDemoStep } from './BrowserDemoActivity'

describe('describeDemoStep', () => {
  const t = (key: string): string => key

  it('shows scrolling, which has no label to name', () => {
    expect(describeDemoStep({ kind: 'scroll_to', target: { tag: 'html' } }, t)).toBe('browserDemoStepScrollPage')
    expect(describeDemoStep({ kind: 'scroll_to', target: { tag: 'div' } }, t)).toBe('browserDemoStepScrollPanel')
  })
})

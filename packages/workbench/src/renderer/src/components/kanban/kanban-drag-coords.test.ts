import { describe, expect, it } from 'vitest'
import { layoutPxFromVisual, scaleDndTransform } from './kanban-drag-coords'

describe('layoutPxFromVisual', () => {
  it('keeps pixels when UI scale is 1', () => {
    expect(layoutPxFromVisual(440, 1)).toBe(440)
  })

  it('converts a post-zoom rect into body layout px', () => {
    expect(layoutPxFromVisual(440, 0.88)).toBe(500)
  })
})

describe('scaleDndTransform', () => {
  it('leaves the dnd-kit delta alone at scale 1', () => {
    const transform = { x: 12, y: -4, scaleX: 1, scaleY: 1 }
    expect(scaleDndTransform(transform, 1)).toBe(transform)
  })

  it('scales the delta so the overlay still follows the pointer under body zoom', () => {
    expect(scaleDndTransform({ x: 88, y: 44, scaleX: 1, scaleY: 1 }, 0.88)).toEqual({
      x: 100,
      y: 50,
      scaleX: 1,
      scaleY: 1
    })
  })
})

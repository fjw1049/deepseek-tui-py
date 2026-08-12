import { describe, expect, it } from 'vitest'
import {
  rightSidebarTabBarPlanForTier,
  rightSidebarTabBarPlanForWidth,
  rightSidebarTabBarTierForWidth
} from './right-sidebar-tab-bar-layout'

describe('rightSidebarTabBarPlanForWidth', () => {
  it('keeps all labeled tabs while there is still room', () => {
    expect(rightSidebarTabBarTierForWidth(null)).toBe(0)
    // Plenty of empty space — must not hide yet.
    expect(rightSidebarTabBarTierForWidth(300)).toBe(0)
    expect(rightSidebarTabBarTierForWidth(270)).toBe(0)
    const plan = rightSidebarTabBarPlanForWidth(300, 'terminal')
    expect(plan.visibleTabs).toEqual(['editor', 'changes', 'terminal', 'preview'])
    expect(plan.showLabel).toEqual({
      editor: true,
      changes: true,
      terminal: true,
      preview: true
    })
  })

  it('hides labels from the left only near collision', () => {
    expect(rightSidebarTabBarTierForWidth(260)).toBe(1)
    expect(rightSidebarTabBarPlanForWidth(260, 'terminal').showLabel).toEqual({
      editor: false,
      changes: true,
      terminal: true,
      preview: true
    })

    expect(rightSidebarTabBarPlanForWidth(240, 'terminal').showLabel).toEqual({
      editor: false,
      changes: false,
      terminal: true,
      preview: true
    })

    expect(rightSidebarTabBarPlanForWidth(220, 'terminal').showLabel).toEqual({
      editor: false,
      changes: false,
      terminal: false,
      preview: true
    })

    expect(rightSidebarTabBarPlanForWidth(200, 'terminal').showLabel).toEqual({
      editor: false,
      changes: false,
      terminal: false,
      preview: false
    })
  })

  it('hides inactive tabs from the left after labels are gone', () => {
    expect(rightSidebarTabBarPlanForWidth(140, 'terminal').visibleTabs).toEqual([
      'changes',
      'terminal',
      'preview'
    ])

    expect(rightSidebarTabBarPlanForWidth(110, 'terminal').visibleTabs).toEqual([
      'terminal',
      'preview'
    ])

    expect(rightSidebarTabBarPlanForWidth(90, 'terminal').visibleTabs).toEqual([
      'terminal',
      'preview'
    ])

    // Active terminal stays even when its slot would be hidden.
    expect(rightSidebarTabBarPlanForWidth(70, 'terminal').visibleTabs).toEqual(['terminal'])
  })

  it('never drops the active tab', () => {
    expect(rightSidebarTabBarPlanForWidth(70, 'editor').visibleTabs).toEqual(['editor'])
    expect(rightSidebarTabBarPlanForWidth(70, 'preview').visibleTabs).toEqual(['preview'])
    expect(rightSidebarTabBarPlanForWidth(110, 'editor').visibleTabs).toContain('editor')
  })

  it('tier helper matches width ladder', () => {
    for (const tier of [0, 1, 2, 3, 4, 5, 6, 7, 8] as const) {
      expect(rightSidebarTabBarPlanForTier(tier, 'terminal')).toEqual(
        rightSidebarTabBarPlanForWidth(
          [268, 267, 247, 227, 207, 147, 121, 97, 77][tier],
          'terminal'
        )
      )
    }
  })
})

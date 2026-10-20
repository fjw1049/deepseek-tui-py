// @vitest-environment happy-dom
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { SkillSourceStack } from './SkillSourceIcon'

describe('SkillSourceStack', () => {
  it.each([1, 2, 3, 4, 5, 6, 7, 8])('keeps all %i sources in their original order', (count) => {
    const sources = ['claude', 'codex', 'cursor', 'qwen', 'gemini', 'codebuddy', 'opencode', 'deepseek']
    const host = document.createElement('div')
    host.innerHTML = renderToStaticMarkup(createElement(SkillSourceStack, {
      paths: sources.slice(0, count).map((source) => `/home/.${source}/skills/demo/SKILL.md`)
    }))
    const tiles = [...host.querySelectorAll<HTMLElement>('.ds-skill-source-stack__tile')]
    expect(tiles).toHaveLength(count)
    expect(tiles.map((tile) => tile.style.getPropertyValue('--source-index')))
      .toEqual(Array.from({ length: count }, (_, index) => String(index)))
    expect(tiles.map((tile) => tile.querySelector('.ds-skill-brand')?.getAttribute('data-brand')))
      .toEqual(sources.slice(0, count).map((source) =>
        source === 'opencode' || source === 'deepseek' ? 'own' : source))
    const angles = tiles.map((tile) => parseFloat(tile.style.getPropertyValue('--source-angle')))
    expect(Math.max(...angles) - Math.min(...angles)).toBeLessThanOrEqual(36)
    const stack = host.querySelector<HTMLElement>('.ds-skill-source-stack')!
    expect(parseFloat(stack.style.getPropertyValue('--source-spread'))).toBeLessThan(72)
    expect(tiles[0].querySelector<HTMLElement>('.ds-skill-brand')?.style.width)
      .toBe(count === 1 ? '40px' : '32px')
  })
})

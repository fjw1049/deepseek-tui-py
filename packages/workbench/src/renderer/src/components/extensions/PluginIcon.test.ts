import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { PluginIcon } from './PluginIcon'

it('keeps gradient references local when list and detail icons render together', () => {
  const ids = ['computer-use', 'deep-research', 'data-analysis', 'document-process']
  const html = renderToStaticMarkup(createElement('div', null,
    [...ids, ...ids].map((pluginId, index) => createElement(PluginIcon, { pluginId, key: index }))))
  const gradientIds = [...html.matchAll(/id="([^"]+)"/g)].map(match => match[1])
  expect(gradientIds).toHaveLength(16)
  expect(new Set(gradientIds).size).toBe(16)
  for (const svg of html.matchAll(/<svg\b[\s\S]*?<\/svg>/g)) {
    for (const reference of svg[0].matchAll(/url\(#([^)]*)\)/g)) {
      expect(svg[0]).toContain(`id="${reference[1]}"`)
    }
  }
})

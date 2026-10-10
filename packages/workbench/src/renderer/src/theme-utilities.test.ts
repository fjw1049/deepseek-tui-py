import { fileURLToPath } from 'node:url'
import postcss from 'postcss'
import tailwindcss from 'tailwindcss'
import loadConfig from 'tailwindcss/loadConfig'
import { expect, it } from 'vitest'

it('generates translucent theme backgrounds and accent focus rings from the active palette', async () => {
  const config = loadConfig(fileURLToPath(new URL('../../../tailwind.config.js', import.meta.url)))
  const result = await postcss([tailwindcss({
    ...config,
    content: [{ raw: '<div class="bg-ds-main/45 border-ds-border/60 focus-within:ring-accent/30 text-ds-muted/70"></div>' }]
  })]).process('@tailwind utilities;', { from: undefined })

  for (const className of ['bg-ds-main\\/45', 'border-ds-border\\/60', 'focus-within\\:ring-accent\\/30', 'text-ds-muted\\/70']) {
    expect(result.css, className).toContain(`.${className}`)
  }
  expect(result.css).toContain('var(--ds-accent)')
  expect(result.css).toContain('color-mix(in srgb,')
})

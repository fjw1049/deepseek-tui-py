import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { buildChromeThemeCssVars } from '@shared/appearance-derive'
import { getThemePresetSeed } from '@shared/appearance'

const stylesheet = readFileSync(new URL('./index.css', import.meta.url), 'utf8')
const mainProcessSource = readFileSync(new URL('../../main/index.ts', import.meta.url), 'utf8')
const workbenchSource = readFileSync(new URL('./components/Workbench.tsx', import.meta.url), 'utf8')

describe('macOS translucent sidebar material', () => {
  it('uses one continuous native material plane for the Nord sidebar and window corners', () => {
    const seed = getThemePresetSeed('nord', 'dark')!
    const translucent = buildChromeThemeCssVars({ ...seed, translucent: true }, 'dark')
    const opaque = buildChromeThemeCssVars({ ...seed, translucent: false }, 'dark')

    expect(translucent['--app-window-background']).toBe('transparent')
    expect(translucent['--app-shell-background']).toBe(translucent['--glass-bg'])
    expect(translucent['--app-sidebar-surface']).toBe('transparent')
    expect(translucent['--app-sidebar-backdrop-filter']).toBe('none')
    expect(translucent['--app-chrome-fill']).toBe('transparent')
    expect(translucent['--app-corner-surface']).toBe('transparent')

    expect(opaque['--app-window-background']).toBe(opaque['--bg-app'])
    expect(opaque['--app-shell-background']).toBe(opaque['--bg-app'])
    expect(opaque['--app-sidebar-surface']).toBe(opaque['--bg-sidebar'])
    expect(opaque['--app-sidebar-backdrop-filter']).toBe('none')
    expect(opaque['--app-chrome-fill']).toBe(opaque['--bg-sidebar'])
    expect(opaque['--app-corner-surface']).toBe(opaque['--bg-sidebar'])
  })

  it('leaves the already-correct light translucent composition unchanged', () => {
    const seed = getThemePresetSeed('notion', 'light')!
    const translucent = buildChromeThemeCssVars({ ...seed, translucent: true }, 'light')

    expect(translucent['--app-window-background']).toBe('transparent')
    expect(translucent['--app-shell-background']).toBe('transparent')
    expect(translucent['--app-sidebar-surface']).toBe(translucent['--glass-bg'])
    expect(translucent['--app-sidebar-backdrop-filter']).toBe('blur(8px) saturate(135%)')
    expect(translucent['--app-chrome-fill']).toBe(translucent['--bg-sidebar'])
    expect(translucent['--app-corner-surface']).toBe(translucent['--bg-sidebar'])
  })

  it('connects those tokens to the macOS shell while keeping other platforms opaque', () => {
    const macWindowRule = stylesheet.match(
      /:root\[data-platform='darwin'\] body,(?:\s*):root\[data-platform='darwin'\] body::before \{(?<body>[^}]*)\}/
    )?.groups?.body
    expect(macWindowRule).toContain('background: var(--app-window-background);')

    const macShellRule = stylesheet.match(
      /:root\[data-platform='darwin'\] \.ds-workbench-shell \{(?<body>[^}]*)\}/
    )?.groups?.body
    expect(macShellRule).toContain('background: var(--app-shell-background);')

    const macSidebarRule = stylesheet.match(
      /:root\[data-platform='darwin'\] \.ds-sidebar-shell \{(?<body>[^}]*)\}/
    )?.groups?.body
    expect(macSidebarRule).toContain('background: var(--app-sidebar-surface);')
    expect(macSidebarRule).toContain('backdrop-filter: var(--app-sidebar-backdrop-filter);')

    const baseSidebarRule = stylesheet.match(/\.ds-sidebar-shell \{(?<body>[^}]*)\}/)?.groups?.body
    expect(baseSidebarRule).toContain('background: var(--bg-sidebar);')
    expect(baseSidebarRule).toContain('backdrop-filter: none;')
  })

  it('keeps opaque gutters solid but lets the continuous material show through when enabled', () => {
    const chromeFillRule = stylesheet.match(
      /:root\[data-platform='darwin'\] \.ds-workbench-shell::before \{(?<body>[^}]*)\}/
    )?.groups?.body
    expect(chromeFillRule).toContain('position: absolute;')
    expect(chromeFillRule).toContain('background: var(--app-chrome-fill);')
    expect(chromeFillRule).toContain('transition: left 300ms cubic-bezier(0.32, 0.72, 0, 1);')
    expect(chromeFillRule).toContain('left: var(--ds-sidebar-width, 0px);')

    const macWedgeRule = stylesheet.match(
      /:root\[data-platform='darwin'\] \.ds-workbench-sidebar-wrap::after \{(?<body>[^}]*)\}/
    )?.groups?.body
    expect(macWedgeRule).toContain('background: var(--app-corner-surface);')
    expect(workbenchSource).toContain("'--ds-sidebar-width':")
  })

  it('creates the macOS window over the native under-window material', () => {
    expect(mainProcessSource).toContain("vibrancy: 'under-window'")
    expect(mainProcessSource).toContain("visualEffectState: 'followWindow'")
    expect(mainProcessSource).toContain("backgroundColor: '#00000000'")
  })
})

describe('settings select material', () => {
  it('keeps the options menu opaque over settings controls', () => {
    const menuRule = stylesheet.match(/\.ds-settings-select-menu \{(?<body>[^}]*)\}/)?.groups?.body
    expect(menuRule).toContain('background: var(--ds-surface-elevated, #fff);')
    expect(menuRule).toContain('backdrop-filter: none;')

    const darkMenuRule = stylesheet.match(
      /\[data-theme='dark'\] \.ds-settings-select-menu \{(?<body>[^}]*)\}/
    )?.groups?.body
    expect(darkMenuRule).toContain('background: var(--ds-surface-elevated, #1c1c1e);')
  })
})

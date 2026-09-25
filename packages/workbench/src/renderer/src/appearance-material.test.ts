import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { buildChromeThemeCssVars } from '@shared/appearance-derive'
import { getThemePresetSeed, listThemePresetsForVariant } from '@shared/appearance'

const stylesheet = readFileSync(new URL('./index.css', import.meta.url), 'utf8')
const mainProcessSource = readFileSync(new URL('../../main/index.ts', import.meta.url), 'utf8')
const workbenchSource = readFileSync(new URL('./components/Workbench.tsx', import.meta.url), 'utf8')

describe('macOS translucent sidebar material', () => {
  it('changes opaque light sidebar and window edges together with contrast', () => {
    const brightness = (color: string): number =>
      0.2126 * Number.parseInt(color.slice(1, 3), 16) +
      0.7152 * Number.parseInt(color.slice(3, 5), 16) +
      0.0722 * Number.parseInt(color.slice(5, 7), 16)
    for (const preset of listThemePresetsForVariant('light')) {
      const seed = getThemePresetSeed(preset.id, 'light')!
      const palettes = [0, 25, 45, 75, 100].map((contrast) =>
        buildChromeThemeCssVars({ ...seed, contrast, translucent: false }, 'light')
      )
      const levels = palettes.map((vars) => brightness(vars['--bg-sidebar']!))
      for (let i = 1; i < levels.length; i++) {
        expect(levels[i - 1]! - levels[i]!, preset.id).toBeGreaterThan(4)
      }
      expect(levels[0]! - levels[4]!, preset.id).toBeGreaterThan(34)
      for (const vars of palettes) {
        for (const token of ['--app-shell-background', '--app-sidebar-surface', '--app-chrome-fill', '--app-corner-surface']) {
          expect(vars[token], `${preset.id}: ${token}`).toBe(vars['--bg-sidebar'])
        }
        expect(vars['--ds-material-panel']).toBe(seed.surface)
      }
    }
  })

  it('visibly changes light glass with contrast while keeping the reading surface fixed', () => {
    // Composite over a white native backdrop: even without wallpaper colors,
    // increasing contrast must visibly separate the shell from the canvas.
    const brightnessOverWhite = (color: string): number => {
      const [r, g, b, alpha] = color.match(/[\d.]+/g)!.map(Number)
      return (0.2126 * r! + 0.7152 * g! + 0.0722 * b!) * alpha! + 255 * (1 - alpha!)
    }
    for (const preset of listThemePresetsForVariant('light')) {
      const seed = getThemePresetSeed(preset.id, 'light')!
      const palettes = [0, 25, 45, 75, 100].map((contrast) =>
        buildChromeThemeCssVars({ ...seed, contrast, translucent: true }, 'light')
      )
      const levels = palettes.map((vars) => brightnessOverWhite(vars['--app-shell-background']!))
      for (let i = 1; i < levels.length; i++) {
        expect(levels[i - 1]! - levels[i]!, preset.id).toBeGreaterThan(4)
      }
      // Tinted presets have a smaller ink/surface gap than black on white.
      expect(levels[0]! - levels[4]!, preset.id).toBeGreaterThan(23)
      for (const vars of palettes) {
        expect(vars['--ds-material-panel']).toBe(seed.surface)
        expect(vars['--app-sidebar-surface']).toBe('transparent')
        expect(vars['--app-corner-surface']).toBe('transparent')
      }
    }
  })

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

  it('uses one continuous material plane for high-contrast light glass', () => {
    const seed = getThemePresetSeed('notion', 'light')!
    const translucent = buildChromeThemeCssVars(
      { ...seed, contrast: 100, translucent: true },
      'light'
    )

    expect(translucent['--app-window-background']).toBe('transparent')
    expect(translucent['--app-shell-background']).toBe(translucent['--glass-bg'])
    expect(translucent['--app-sidebar-surface']).toBe('transparent')
    expect(translucent['--app-sidebar-backdrop-filter']).toBe('none')
    expect(translucent['--app-chrome-fill']).toBe('transparent')
    expect(translucent['--app-corner-surface']).toBe('transparent')
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

describe('light change inspector reading surface', () => {
  it('isolates diff content and nested headers from the sidebar contrast tint', () => {
    const rule = stylesheet.match(
      /\[data-theme='light'\] \.ds-change-inspector,\s*\[data-theme='light'\] \.ds-workspace-editor-pane,\s*\[data-theme='light'\] \.ds-diff-view--flush \{(?<body>[^}]*)\}/
    )?.groups?.body
    expect(rule).toContain('--ds-bg-sidebar: var(--ds-bg-canvas);')
    // The local alias also covers the more specific right-panel background,
    // file-list group headers, and the flush diff's own header.
    for (const selector of ['.ds-change-inspector', '.ds-diff-view--flush', '.ds-change-inspector__pane-header', '.ds-diff-view--flush .ds-diff-view__header']) {
      const start = stylesheet.indexOf(`\n${selector} {`)
      const body = stylesheet.slice(start, stylesheet.indexOf('}', start))
      expect(body, selector).toContain('background: var(--ds-bg-sidebar);')
    }
  })
})

describe('native window drag targets', () => {
  it('keeps an unobstructed top-edge drag strip active across transient menus', () => {
    const stripRule = stylesheet.match(
      /\.ds-window-drag-strip \{(?<body>[^}]*)\}/
    )?.groups?.body
    expect(stripRule).toContain('position: absolute;')
    expect(stripRule).toContain('height: var(--ds-window-inset, 8px);')
    expect(stripRule).toContain('-webkit-app-region: drag;')
    expect(workbenchSource).toContain('className="ds-window-drag-strip"')

    const lightDismissRule = stylesheet.match(
      /html\.ds-light-dismiss-active \.ds-window-drag-strip,[^{]*\{(?<body>[^}]*)\}/
    )?.groups?.body
    expect(lightDismissRule).toContain('-webkit-app-region: drag !important;')
  })
})

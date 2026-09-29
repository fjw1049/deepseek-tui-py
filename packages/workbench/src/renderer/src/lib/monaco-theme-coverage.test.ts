// @vitest-environment happy-dom
import * as monaco from 'monaco-editor'
import { beforeAll, describe, expect, it } from 'vitest'
import { CODE_PALETTE, MONACO_SCOPE_SLOTS, SHIKI_SCOPE_SLOTS } from './code-palette'
import { themeRules } from './monaco-editor-setup'
import { LEXICAL_PROFILES } from './monaco-lexical-semantic-tokens'

const hex = (color: string): number[] => [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16) / 255)
const toLinear = (c: number): number => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
const relativeLuminance = (color: string): number => {
  const [r, g, b] = hex(color).map(toLinear)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
/** WCAG contrast ratio against an opaque background. */
function contrast(a: string, b: string): number {
  const [hi, lo] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}
/** OKLab distance: how different two colors *look*, not how different they read. */
function perceptualDistance(a: string, b: string): number {
  const lab = (color: string): number[] => {
    const [r, g, b2] = hex(color).map(toLinear)
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b2)
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b2)
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b2)
    return [
      0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
      1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
      0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s
    ]
  }
  const [x, y] = [lab(a), lab(b)]
  return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2])
}

// The harder of the two light surfaces: chat blocks sit on pure white, the
// workspace panel on a tint. Guard the tint, and white passes with room.
const BACKGROUND = { light: '#f0f0f0', dark: '#181818' } as const
/** Comments are de-emphasized by convention, so they are exempt from the floor. */
const DE_EMPHASIZED = new Set(['ink', 'punctuation', 'comment'])



// Monaco's basic-languages grammars register lazily — a language only tokenizes
// once a model with that id exists — so the first tokenize of a language is
// retried until its grammar lands.
async function tokenTypes(languageId: string, code: string): Promise<string[]> {
  const model = monaco.editor.createModel(code, languageId)
  try {
    for (let attempt = 0; attempt < 200; attempt++) {
      // Until the grammar lands, every line yields one empty-type token.
      const types = [
        ...new Set(
          monaco.editor
            .tokenize(code, languageId)
            .flat()
            .map((token) => token.type)
            .filter(Boolean)
        )
      ]
      if (types.length > 0) return types
      await new Promise((resolve) => setTimeout(resolve, 15))
    }
    return []
  } finally {
    model.dispose()
  }
}

/** Monaco matches a token by walking its dotted prefixes, longest first. */
function matches(declared: readonly string[], token: string): boolean {
  const parts = token.split('.')
  for (let length = parts.length; length > 0; length--) {
    if (declared.includes(parts.slice(0, length).join('.'))) return true
  }
  return false
}

const declaredScopes = (appearance: 'light' | 'dark'): string[] =>
  themeRules(appearance)
    .map((rule) => rule.token)
    .filter((token) => token !== '')

// One sample per language that exercised the gaps this change fills. The
// expected scopes are asserted to come out of Monaco itself, so a grammar that
// renames one fails here instead of going quietly flat. Note the suffixes:
// Monaco's `c` grammar reports `.cpp` scopes, and keywords are usually
// qualified (`keyword.public.java`) rather than bare.
const SAMPLES: { language: string; code: string; scopes: string[] }[] = [
  {
    language: 'go',
    code: 'package main\n\ntype Point struct{ X int }\n\nfunc (p Point) Sum() int { return p.X }\n',
    scopes: ['keyword.func.go', 'keyword.struct.go', 'delimiter.go', 'identifier.go']
  },
  {
    language: 'java',
    code: '@Override\npublic void run() {}\n',
    scopes: ['annotation.java', 'keyword.public.java', 'delimiter.curly.java']
  },
  {
    language: 'javascript',
    code: 'const re = /[a-z]+/g\nfunction f(x) { return x }\n',
    scopes: ['regexp.js', 'regexp.escape.control.js', 'keyword.other.js']
  },
  {
    language: 'ini',
    code: '; comment\n[section]\nkey = value\n',
    scopes: ['key.ini', 'metatag.ini', 'comment.ini']
  },
  {
    language: 'html',
    code: '<div class="x" data-id="1">text</div>\n',
    scopes: ['attribute.name.html', 'attribute.value.html', 'tag.html']
  },
  {
    language: 'xml',
    code: '<?xml version="1.0"?>\n<root attr="1">x</root>\n',
    scopes: ['metatag.xml', 'attribute.value.xml', 'tag.xml']
  },
  {
    language: 'sql',
    code: 'SELECT count(*) FROM users WHERE id = 1;\n',
    scopes: ['predefined.sql', 'number.sql', 'keyword.sql']
  },
  {
    language: 'markdown',
    code: '**bold** _em_ [link](https://example.com)\n',
    scopes: ['strong.md', 'emphasis.md', 'string.link.md']
  },
  {
    language: 'c',
    code: '#define MAX 3\n#include <stdio.h>\nint main(void) { return 0; }\n',
    scopes: ['keyword.directive.cpp', 'string.include.identifier.cpp', 'number.cpp']
  },
  {
    language: 'rust',
    code: 'pub fn parse(x: &str) -> u8 { 0 }\n',
    scopes: ['keyword.rust', 'keyword.type.rust', 'number.rust']
  },
  {
    language: 'shell',
    code: '#!/bin/bash\nfoo() { echo "$1"; }\n',
    scopes: ['metatag.shell', 'type.identifier.shell', 'string.shell']
  },
  {
    language: 'yaml',
    code: 'key: value\nlist:\n  - a\n',
    scopes: ['type.yaml', 'string.yaml']
  }
]

describe('monaco theme coverage', () => {
  beforeAll(() => {
    // Creating a JS model starts Monaco's TypeScript diagnostics, which spawns
    // a real Worker — undefined here, so the rejection escapes as unhandled. A
    // stub that never answers is all a tokenization-only test needs.
    globalThis.Worker = class {
      postMessage(): void {}
      addEventListener(): void {}
      removeEventListener(): void {}
      terminate(): void {}
    } as unknown as typeof Worker

    monaco.editor.defineTheme('coverage-dark', {
      base: 'vs-dark',
      inherit: true,
      rules: themeRules('dark'),
      colors: {}
    })
  })

  it.each(SAMPLES)('declares a rule for every scope $language emits', async ({ language, code, scopes }) => {
    const emitted = await tokenTypes(language, code)
    expect(emitted.length).toBeGreaterThan(0)
    for (const scope of scopes) expect(emitted).toContain(scope)
    const uncovered = emitted.filter((scope) => !matches(declaredScopes('dark'), scope))
    // Deliberately ink, so no rule is expected: plain names are colored by the
    // lexical provider, and whitespace/operators stay ink just as in VS Code.
    expect(uncovered.filter((scope) => !/^(identifier|white|operator)/.test(scope))).toEqual([])
  }, 30000)

  it('keeps both appearances on the same scope set', () => {
    expect(declaredScopes('light')).toEqual(declaredScopes('dark'))
  })

  it('keeps every slot legible and visibly colored on its own background', () => {
    for (const appearance of ['light', 'dark'] as const) {
      const slots = CODE_PALETTE[appearance]
      const ink = slots.ink.color
      for (const [slot, style] of Object.entries(slots)) {
        expect(style.color, `${appearance}/${slot}`).toMatch(/^#[0-9a-f]{6}$/)
        // Punctuation is ink by design; everything else has to be readable…
        if (DE_EMPHASIZED.has(slot)) continue
        expect(
          contrast(style.color, BACKGROUND[appearance]),
          `${appearance}/${slot} contrast`
        ).toBeGreaterThanOrEqual(4.5)
        // …and far enough from body ink to read as a *color*. This is where a
        // light palette goes flat: `#0a3069` cleared 12:1 yet sat a hair from
        // `#24292f`, so strings read as plain text.
        expect(
          perceptualDistance(style.color, ink),
          `${appearance}/${slot} vs ink`
        ).toBeGreaterThanOrEqual(0.15)
      }
    }
  })

  it('registers a lexical profile under a language id Monaco actually has', () => {
    const known = new Set(monaco.languages.getLanguages().map((language) => language.id))
    // A wrong key is silent: no model ever carries that id, so the provider is
    // never asked and the language just stays flat.
    expect(Object.keys(LEXICAL_PROFILES).filter((id) => !known.has(id))).toEqual([])
  })

  it('maps every chat scope onto a slot the palette defines', () => {
    for (const [scope, slot] of SHIKI_SCOPE_SLOTS) {
      expect(CODE_PALETTE.dark[slot], scope).toBeDefined()
      expect(CODE_PALETTE.light[slot], scope).toBeDefined()
    }
    // The Monaco table is the union of scope names plus the semantic types.
    expect(MONACO_SCOPE_SLOTS.map(([token]) => token)).toContain('annotation')
  })
})

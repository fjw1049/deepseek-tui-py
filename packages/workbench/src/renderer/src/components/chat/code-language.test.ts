import { expect, it } from 'vitest'
import { languageFromPath, normalizeLanguage } from './code-language'

it.each([
  // The editor gives up on these; the chat surface hands Shiki a bare name.
  ['Makefile', 'makefile'],
  ['GNUmakefile', 'makefile'],
  ['CMakeLists.txt', 'cmake'],
  // Everything else defers to the shared resolver.
  ['src/app.ts', 'typescript'],
  ['main.go', 'go'],
  ['Dockerfile', 'dockerfile'],
  ['internal/api.proto', 'proto']
])('resolves %s to %s for Shiki', (path, expected) => {
  expect(languageFromPath(path)).toBe(expected)
})

it('keeps Monaco-only aliases out of the Shiki language ids', () => {
  expect(normalizeLanguage('shellscript')).toBe('shell')
  expect(normalizeLanguage('plaintext')).toBe('')
})

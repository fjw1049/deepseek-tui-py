import { expect, it } from 'vitest'
import { languageForPath } from './monaco-language-for-path'

it.each([
  ['src/App.java', 'java'], ['main.cpp', 'cpp'], ['main.c', 'c'],
  ['db/query.sql', 'sql'], ['Dockerfile', 'dockerfile'], ['Dockerfile.dev', 'dockerfile'],
  ['C:\\project\\App.CS', 'csharp'], ['.env.local', 'ini'], ['.zshrc', 'shell'],
  ['types.pyi', 'python'], ['config.jsonc', 'json'], ['main.tf', 'hcl'],
  ['App.vue', 'html'], ['README.md', 'markdown'], ['main.tsx', 'typescript'],
  ['notes.unknown', 'plaintext']
])('recognizes %s as %s', (path, expected) => {
  expect(languageForPath(path)).toBe(expected)
})

import { describe, expect, it } from 'vitest'
import { isMaterialRecognizedFile, materialIconNameForPath } from './file-icon'

describe('material file icons', () => {
  it('maps common and uncommon languages from the VS Code theme', () => {
    expect(materialIconNameForPath('src/app.ts')).toBe('typescript')
    expect(materialIconNameForPath('src/app.tsx')).toBe('react_ts')
    expect(materialIconNameForPath('lib/main.dart')).toBe('dart')
    expect(materialIconNameForPath('lib/app.ex')).toBe('elixir')
    expect(materialIconNameForPath('cmd/main.go')).toBe('go')
    expect(materialIconNameForPath('pkg/lib.rs')).toBe('rust')
    expect(materialIconNameForPath('src/Main.kt')).toBe('kotlin')
    expect(materialIconNameForPath('Dockerfile')).toBe('docker')
    expect(materialIconNameForPath('package.json')).toBe('nodejs')
  })

  it('falls back to the generic file icon instead of dropping unknown types', () => {
    expect(materialIconNameForPath('notes.unknownxyz')).toBe('file')
    expect(isMaterialRecognizedFile('notes.unknownxyz')).toBe(false)
    expect(isMaterialRecognizedFile('main.dart')).toBe(true)
  })

  it('maps folders from the theme, including open state', () => {
    expect(materialIconNameForPath('src', { directory: true })).toBe('folder-src')
    expect(materialIconNameForPath('src', { directory: true, expanded: true })).toBe(
      'folder-src-open'
    )
    expect(materialIconNameForPath('mystery-dir', { directory: true })).toBe('folder')
    expect(materialIconNameForPath('mystery-dir', { directory: true, expanded: true })).toBe(
      'folder-open'
    )
  })
})

// @vitest-environment happy-dom
import * as monaco from 'monaco-editor'
import { expect, it, vi } from 'vitest'
import { prepareWorkspaceLanguage } from './monaco-editor-setup'

it('shares language preparation and skips it once ready, with retry after failure', async () => {
  let finish!: (value: string) => void
  const colorize = vi.spyOn(monaco.editor, 'colorize').mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  try {
    const first = prepareWorkspaceLanguage('python')
    expect(prepareWorkspaceLanguage('python')).toBe(first)
    finish('')
    await first
    await prepareWorkspaceLanguage('python')
    expect(colorize).toHaveBeenCalledTimes(1)
    expect(colorize).toHaveBeenCalledWith('', 'python', {})
    colorize.mockRejectedValueOnce(new Error('failed'))
    await expect(prepareWorkspaceLanguage('ruby')).rejects.toThrow('failed')
    colorize.mockResolvedValueOnce('')
    await prepareWorkspaceLanguage('ruby')
  } finally { colorize.mockRestore() }
})

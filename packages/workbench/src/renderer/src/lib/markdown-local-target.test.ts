import { expect, it } from 'vitest'
import { markdownLocalTarget } from './markdown-local-target'
import { languageFromPath } from '../components/chat/code-language'

it('resolves document assets and fragments on POSIX and Windows', () => {
  expect(markdownLocalTarget('../images/a%20b.png', 'docs/guide.md', '/project')).toEqual({ path: '/project/images/a b.png', fragment: '' })
  expect(markdownLocalTarget('next.md#使用方法', '/project/docs/start.md', '/project')).toEqual({ path: '/project/docs/next.md', fragment: '使用方法' })
  expect(markdownLocalTarget('images/a.png', 'C:\\project\\README.md', 'C:\\project')).toEqual({ path: 'C:/project/images/a.png', fragment: '' })
  expect(markdownLocalTarget('https://example.com', 'README.md', '/project')).toBeNull()
  expect(markdownLocalTarget('javascript:alert(1)', 'README.md', '/project')).toBeNull()
  expect(markdownLocalTarget('%ZZ.png', 'README.md', '/project')).toBeNull()
})

it('shares file language detection while preserving specialized Shiki grammars', () => {
  expect(languageFromPath('Dockerfile')).toBe('dockerfile')
  expect(languageFromPath('types.pyi')).toBe('python')
  expect(languageFromPath('main.tf')).toBe('hcl')
  expect(languageFromPath('App.vue')).toBe('vue')
  expect(languageFromPath('App.tsx')).toBe('tsx')
  expect(languageFromPath('README')).toBe('')
})

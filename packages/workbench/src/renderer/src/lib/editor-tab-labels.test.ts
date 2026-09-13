import { expect, it } from 'vitest'
import { editorTabParentLabels } from './editor-tab-labels'

it('leaves unique filenames uncluttered', () => {
  expect(editorTabParentLabels(['/root/app.ts', '/root/test.ts']).size).toBe(0)
})

it('uses only enough parent segments to distinguish repeated names', () => {
  const paths = ['/root/one/src/index.ts', '/root/two/src/index.ts', '/root/lib/index.ts']
  expect([...editorTabParentLabels(paths).values()]).toEqual(['one/src', 'two/src', 'lib'])
})

it('handles a parent that is a suffix of another parent and Windows paths', () => {
  const paths = ['C:\\src\\index.ts', 'C:\\app\\src\\index.ts']
  expect([...editorTabParentLabels(paths).values()]).toEqual(['C:/src', 'app/src'])
})

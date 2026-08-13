import { describe, expect, it } from 'vitest'
import { collapseBreadcrumbSegments, splitFileNameAndParent } from './editor-breadcrumb'

describe('splitFileNameAndParent', () => {
  it('splits a nested relative path', () => {
    expect(splitFileNameAndParent('src/lib/foo.ts')).toEqual({
      name: 'foo.ts',
      parent: 'src/lib'
    })
  })

  it('returns an empty parent for a bare file', () => {
    expect(splitFileNameAndParent('README.md')).toEqual({
      name: 'README.md',
      parent: ''
    })
  })
})

describe('collapseBreadcrumbSegments', () => {
  it('keeps short trails intact', () => {
    expect(collapseBreadcrumbSegments(['demo', 'src', 'foo.ts'])).toEqual([
      'demo',
      'src',
      'foo.ts'
    ])
  })

  it('collapses the middle instead of truncating a folder name', () => {
    expect(
      collapseBreadcrumbSegments(['demo', 'packages', 'workbench', 'src', 'foo.ts'])
    ).toEqual(['demo', '…', 'src', 'foo.ts'])
  })
})

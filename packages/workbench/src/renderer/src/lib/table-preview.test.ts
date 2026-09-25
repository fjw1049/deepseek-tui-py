import { expect, it } from 'vitest'
import { parseTablePreview, tableColumnLabel } from './table-preview'

it('preserves quoted delimiters, line breaks, escaped quotes, empty fields and BOM', () => {
  expect(parseTablePreview('\uFEFFname,note,value\r\n"A,B","first\nsecond",\r\nC,"say ""hi""",001', 'a.csv')).toEqual([
    ['name', 'note', 'value'], ['A,B', 'first\nsecond', ''], ['C', 'say "hi"', '001']
  ])
  expect(parseTablePreview('a\tb\n1\t2', 'a.TSV')).toEqual([['a', 'b'], ['1', '2']])
  expect(parseTablePreview('', 'a.csv')).toEqual([])
  expect([0, 25, 26, 49].map(tableColumnLabel)).toEqual(['A', 'Z', 'AA', 'AX'])
})

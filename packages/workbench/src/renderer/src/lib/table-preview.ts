import { csvParseRows, tsvParseRows } from 'd3-dsv'

export function parseTablePreview(content: string, path: string): string[][] {
  const parse = /\.tsv$/i.test(path) ? tsvParseRows : csvParseRows
  return parse(content.replace(/^\uFEFF/, ''))
}

export function tableColumnLabel(index: number): string {
  let label = ''
  for (let value = index + 1; value > 0; value = Math.floor((value - 1) / 26)) {
    label = String.fromCharCode(65 + (value - 1) % 26) + label
  }
  return label
}

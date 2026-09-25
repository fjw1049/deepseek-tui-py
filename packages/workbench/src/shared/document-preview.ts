export function isPdfPreviewPath(path: string): boolean {
  return /\.pdf$/i.test(path.trim())
}

export function isTablePreviewPath(path: string): boolean {
  return /\.(csv|tsv)$/i.test(path.trim())
}

export function isAllowedSpritesheetUrl(url: string): boolean {
  try {
    const parsed = new URL(url)
    if (parsed.protocol !== 'https:') return false
    return parsed.hostname.endsWith('.r2.dev')
  } catch {
    return false
  }
}

export function isAllowedManifestUrl(url: string): boolean {
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'https:' && parsed.hostname === 'petdex.crafter.run'
  } catch {
    return false
  }
}

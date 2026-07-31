const MANIFEST_HOSTS = new Set(['petdex.dev', 'petdex.crafter.run', 'assets.petdex.dev'])

function isHttpsUrl(url: string): URL | null {
  try {
    const parsed = new URL(url)
    if (parsed.protocol !== 'https:') return null
    return parsed
  } catch {
    return null
  }
}

export function isAllowedSpritesheetUrl(url: string): boolean {
  const parsed = isHttpsUrl(url)
  if (!parsed?.hostname) return false
  // Petdex migrated sprites from Cloudflare R2 pub hosts to assets.petdex.dev.
  return parsed.hostname === 'assets.petdex.dev' || parsed.hostname.endsWith('.r2.dev')
}

export function isAllowedManifestUrl(url: string): boolean {
  const parsed = isHttpsUrl(url)
  if (!parsed?.hostname) return false
  return MANIFEST_HOSTS.has(parsed.hostname)
}

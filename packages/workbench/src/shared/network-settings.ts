export type NetworkSettings = {
  mode: 'system' | 'direct'
  bypassHosts: string[]
}

/** Accept only exact hosts, never URLs, ports, paths or wildcard rules. */
export function normalizeNetworkHost(value: string): string {
  const host = value.trim().toLowerCase()
  if (!host || /[\s/*?#@\\]/.test(host)) throw new Error('Invalid host')
  const url = new URL(`http://${host}`)
  if (url.port || url.hostname !== host || url.pathname !== '/') throw new Error('Invalid host')
  if (!host.startsWith('[') && (host.length > 253 || !host.replace(/\.$/, '').split('.').every(
    (label) => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label)
  ))) throw new Error('Invalid host')
  return host
}

export function normalizeNetworkSettings(value?: NetworkSettings): NetworkSettings {
  if (!value) return { mode: 'system', bypassHosts: [] }
  if (value.mode !== 'system' && value.mode !== 'direct') throw new Error('Invalid proxy mode')
  if (!Array.isArray(value.bypassHosts) || value.bypassHosts.length > 100) {
    throw new Error('Invalid bypass hosts')
  }
  return { mode: value.mode, bypassHosts: [...new Set(value.bypassHosts.map(normalizeNetworkHost))] }
}

/** Preserve the previous Devpilot workaround only for users of that endpoint. */
export function migrateNetworkSettings(urls: string[]): NetworkSettings {
  const usesDevpilot = urls.some((value) => {
    try { return new URL(value).hostname === 'devpilot.zhonganonline.com' } catch { return false }
  })
  return { mode: 'system', bypassHosts: usesDevpilot ? ['devpilot.zhonganonline.com'] : [] }
}

import type { NetworkSettings } from '../../shared/network-settings'

/** Same rule as the runtime: direct mode and listed hosts skip the system proxy. */
export function probeGoesDirect(url: string, network: NetworkSettings): boolean {
  if (network.mode === 'direct') return true
  try {
    return network.bypassHosts.includes(new URL(url).hostname)
  } catch {
    return false // An invalid address is reported by the request itself.
  }
}

import { expect, it } from 'vitest'
import { probeGoesDirect } from './endpoint-probe-fetch'

it('routes like the runtime: listed hosts and direct mode connect directly', () => {
  const system = { mode: 'system' as const, bypassHosts: ['gw.internal.example', '10.1.2.3', '[::1]'] }
  expect(probeGoesDirect('https://gw.internal.example:8443/v1/chat/completions', system)).toBe(true)
  expect(probeGoesDirect('http://10.1.2.3/v1/messages', system)).toBe(true)
  expect(probeGoesDirect('http://[::1]:8080/v1/chat/completions', system)).toBe(true)
  expect(probeGoesDirect('https://GW.Internal.Example/v1', system)).toBe(true)
  // Exact hosts only, as in the runtime: subdomains and other hosts follow the system proxy.
  expect(probeGoesDirect('https://api.gw.internal.example/v1', system)).toBe(false)
  expect(probeGoesDirect('https://api.openai.com/v1/chat/completions', system)).toBe(false)
  expect(probeGoesDirect('https://api.openai.com/v1', { mode: 'direct', bypassHosts: [] })).toBe(true)
})

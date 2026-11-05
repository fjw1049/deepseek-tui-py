/** Some private gateways require direct access while public APIs need the system proxy. */
export async function fetchEndpointProbe(
  url: string,
  init: RequestInit,
  systemFetch: (url: string, init: RequestInit) => Promise<Response>,
  directFetch: (url: string, init: RequestInit) => Promise<Response>
): Promise<Response> {
  try {
    const response = await systemFetch(url, { ...init, signal: AbortSignal.timeout(15_000) })
    if (![502, 503, 504].includes(response.status)) return response
    await response.body?.cancel()
  } catch {
    // Retry the same endpoint once using the original Node network path.
  }
  return directFetch(url, { ...init, signal: AbortSignal.timeout(15_000) })
}

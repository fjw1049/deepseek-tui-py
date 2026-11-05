export type EndpointProbeProtocol = 'openai' | 'anthropic'

export function buildEndpointProbeUrl(
  protocol: EndpointProbeProtocol,
  baseUrl: string
): string {
  let url = baseUrl.replace(/\/+$/, '')
  if (protocol === 'anthropic') {
    if (url.endsWith('/v1/messages')) {
      // Full Messages URL supplied.
    } else if (url.endsWith('/v1')) {
      url = `${url}/messages`
    } else {
      url = `${url}/v1/messages`
    }
  } else if (/\/v\d+$/.test(url)) {
    url = `${url}/chat/completions`
  } else {
    url = `${url}/v1/chat/completions`
  }
  return url
}

export function buildEndpointProbeBody(
  protocol: EndpointProbeProtocol,
  model: string
): Record<string, unknown> {
  return {
    model,
    messages: [{ role: 'user', content: 'Reply with OK.' }],
    ...(protocol === 'anthropic' ? { max_tokens: 1024 } : {}),
    stream: false
  }
}

export function isEndpointProbeResponse(protocol: EndpointProbeProtocol, body: unknown): boolean {
  if (!body || typeof body !== 'object') return false
  const result = body as Record<string, unknown>
  if (result.error) return false
  if (protocol === 'anthropic') return result.type === 'message' && Array.isArray(result.content)
  return Array.isArray(result.choices) && result.choices.some((choice: unknown) =>
    choice !== null && typeof choice === 'object' &&
    'message' in choice && choice.message !== null && typeof choice.message === 'object'
  )
}

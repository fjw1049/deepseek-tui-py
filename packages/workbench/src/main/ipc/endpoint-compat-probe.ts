export type EndpointProbeProtocol = 'openai' | 'anthropic'
export type EndpointProbeToolChoice = 'forced' | 'auto'

const DEFAULT_TOOL_NAME = 'compat_probe'
/** Thinking models (e.g. kimi-k2.7-code) need headroom before a tool call appears. */
const PROBE_MAX_TOKENS = 1024

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
  model: string,
  toolChoice: EndpointProbeToolChoice,
  toolName = DEFAULT_TOOL_NAME
): Record<string, unknown> {
  const userMessage = `Call ${toolName} with value ok.`
  if (protocol === 'anthropic') {
    return {
      model,
      messages: [{ role: 'user', content: userMessage }],
      max_tokens: PROBE_MAX_TOKENS,
      stream: false,
      tools: [{
        name: toolName,
        description: 'Compatibility probe',
        input_schema: {
          type: 'object',
          properties: { value: { type: 'string' } },
          required: ['value']
        }
      }],
      tool_choice: toolChoice === 'auto'
        ? { type: 'auto' }
        : { type: 'tool', name: toolName }
    }
  }
  return {
    model,
    messages: [{ role: 'user', content: userMessage }],
    max_tokens: PROBE_MAX_TOKENS,
    stream: false,
    tools: [{
      type: 'function',
      function: {
        name: toolName,
        description: 'Compatibility probe',
        parameters: {
          type: 'object',
          properties: { value: { type: 'string' } },
          required: ['value']
        }
      }
    }],
    tool_choice: toolChoice === 'auto'
      ? 'auto'
      : { type: 'function', function: { name: toolName } }
  }
}

export function responseHasProbeToolCall(
  protocol: EndpointProbeProtocol,
  body: Record<string, unknown>,
  toolName = DEFAULT_TOOL_NAME
): boolean {
  if (protocol === 'anthropic') {
    const content = Array.isArray(body.content) ? body.content : []
    return content.some((item) =>
      item && typeof item === 'object' &&
      (item as { type?: unknown }).type === 'tool_use' &&
      (item as { name?: unknown }).name === toolName
    )
  }
  const choices = Array.isArray(body.choices) ? body.choices : []
  const firstChoice = choices[0] as {
    message?: { tool_calls?: Array<{ function?: { name?: string } }> }
  } | undefined
  return firstChoice?.message?.tool_calls?.some(
    (call) => call.function?.name === toolName
  ) === true
}

/** Models like kimi-k2.7-code reject forced tool_choice with HTTP 400. */
export function shouldRetryProbeWithAutoToolChoice(status: number): boolean {
  return status === 400
}

import { describe, expect, it } from 'vitest'
import { buildEndpointProbeBody, buildEndpointProbeUrl, isEndpointProbeResponse } from './endpoint-compat-probe'

describe('endpoint connectivity probe', () => {
  it('preserves versioned provider paths', () => {
    expect(buildEndpointProbeUrl('openai', 'https://example.com/api/coding/v3'))
      .toBe('https://example.com/api/coding/v3/chat/completions')
  })

  it('sends a minimal OpenAI request without tool or token-limit restrictions', () => {
    expect(buildEndpointProbeBody('openai', 'example-model')).toEqual({
      model: 'example-model', messages: [{ role: 'user', content: 'Reply with OK.' }], stream: false
    })
  })

  it('includes the required Anthropic token limit without requesting tools', () => {
    const body = buildEndpointProbeBody('anthropic', 'example-model')
    expect(body.max_tokens).toBe(1024)
    expect(body).not.toHaveProperty('tools')
    expect(body).not.toHaveProperty('tool_choice')
  })

  it('accepts ordinary replies without tool calls', () => {
    expect(isEndpointProbeResponse('openai', { choices: [{ message: { content: 'OK' } }] })).toBe(true)
    expect(isEndpointProbeResponse('anthropic', { type: 'message', content: [{ type: 'text', text: 'OK' }] })).toBe(true)
  })

  it('rejects errors and unrelated successful HTTP responses', () => {
    for (const body of [null, {}, { error: 'bad key' }, { choices: [] }, { choices: [null] }]) {
      expect(isEndpointProbeResponse('openai', body)).toBe(false)
    }
    expect(isEndpointProbeResponse('anthropic', { content: [] })).toBe(false)
  })
})

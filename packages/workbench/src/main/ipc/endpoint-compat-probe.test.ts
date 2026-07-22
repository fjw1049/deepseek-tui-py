import { describe, expect, it } from 'vitest'
import {
  buildEndpointProbeBody,
  buildEndpointProbeUrl,
  responseHasProbeToolCall,
  shouldRetryProbeWithAutoToolChoice
} from './endpoint-compat-probe'

describe('endpoint-compat-probe', () => {
  it('builds openai chat completions url for versioned coding base', () => {
    expect(
      buildEndpointProbeUrl('openai', 'https://ark.cn-beijing.volces.com/api/coding/v3')
    ).toBe('https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions')
  })

  it('uses auto tool_choice string for openai auto probe', () => {
    const body = buildEndpointProbeBody('openai', 'kimi-k2.7-code', 'auto')
    expect(body.tool_choice).toBe('auto')
    expect(body.model).toBe('kimi-k2.7-code')
  })

  it('uses forced function tool_choice for openai forced probe', () => {
    const body = buildEndpointProbeBody('openai', 'glm-5.2', 'forced')
    expect(body.tool_choice).toEqual({
      type: 'function',
      function: { name: 'compat_probe' }
    })
  })

  it('detects openai tool calls', () => {
    expect(responseHasProbeToolCall('openai', {
      choices: [{
        message: {
          tool_calls: [{ function: { name: 'compat_probe' } }]
        }
      }]
    })).toBe(true)
    expect(responseHasProbeToolCall('openai', {
      choices: [{ message: { content: 'hi' } }]
    })).toBe(false)
  })

  it('retries only on HTTP 400', () => {
    expect(shouldRetryProbeWithAutoToolChoice(400)).toBe(true)
    expect(shouldRetryProbeWithAutoToolChoice(401)).toBe(false)
    expect(shouldRetryProbeWithAutoToolChoice(200)).toBe(false)
  })
})

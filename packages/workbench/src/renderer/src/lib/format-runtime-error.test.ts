import { describe, expect, it } from 'vitest'
import { formatRuntimeError, getRuntimeErrorCode } from './format-runtime-error'

describe('formatRuntimeError', () => {
  it('maps SSE auth prefix to runtime_auth_required code', () => {
    const err = new Error('runtime_auth_required: bearer token rejected by /v1/*')
    expect(getRuntimeErrorCode(err)).toBe('runtime_auth_required')
  })

  it('formats SSE auth prefix with the i18n runtimeAuthRequired string', () => {
    const err = new Error('runtime_auth_required: sse error 401')
    const formatted = formatRuntimeError(err)
    expect(formatted).not.toContain('sse error 401')
    expect(formatted.length).toBeGreaterThan(0)
  })

  it('still parses JSON runtime errors', () => {
    const err = new Error(JSON.stringify({ error: 'runtime_auth_required', message: 'nope' }))
    expect(getRuntimeErrorCode(err)).toBe('runtime_auth_required')
  })
})

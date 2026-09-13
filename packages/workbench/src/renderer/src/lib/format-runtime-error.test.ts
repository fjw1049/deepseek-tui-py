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


describe('HTTP error payloads', () => {
  it('reads nested FastAPI errors without rendering objects', () => {
    const error = JSON.stringify({ detail: { error: 'wecom_send_failed', message: 'Bad webhook' } })
    expect(formatRuntimeError(error)).toBe('Bad webhook')
    expect(getRuntimeErrorCode(error)).toBe('wecom_send_failed')
  })
  it('reads validation arrays and string details', () => {
    expect(formatRuntimeError(JSON.stringify({ detail: [{ loc: ['body', 'email'], msg: 'Invalid email' }] }))).toContain('Invalid email')
    expect(formatRuntimeError(JSON.stringify({ detail: 'Recipient missing' }))).toBe('Recipient missing')
  })
  it('always returns text for malformed or unexpected payloads', () => {
    for (const value of [null, { error: 500 }, { message: {} }, '<html>Bad gateway</html>', '{broken']) {
      expect(typeof formatRuntimeError(value)).toBe('string')
    }
  })
})

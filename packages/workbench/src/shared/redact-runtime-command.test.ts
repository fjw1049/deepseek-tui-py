import { expect, it } from 'vitest'
import { redactRuntimeCommand } from './redact-runtime-command'

it('redacts separate, equals and quoted credentials while retaining useful arguments', () => {
  expect(redactRuntimeCommand('python --auth-token secret --port 7878 --api-key="key value"'))
    .toBe('python --auth-token [redacted] --port 7878 --api-key=[redacted]')
  expect(redactRuntimeCommand('DEEPSEEK_API_KEY=secret python --runtime-token=another'))
    .toBe('DEEPSEEK_API_KEY=[redacted] python --runtime-token=[redacted]')
})

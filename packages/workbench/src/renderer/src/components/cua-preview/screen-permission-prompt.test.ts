// @vitest-environment happy-dom
import { expect, it } from 'vitest'
import { claimScreenPermissionPrompt } from './screen-permission-prompt'

it('does not ask again across tasks until a verified grant is later lost', () => {
  const p = { appName: 'App', appId: 'test-app-1', status: 'denied' }
  expect(claimScreenPermissionPrompt(p)).toBe(true)
  expect(claimScreenPermissionPrompt(p)).toBe(false)
  expect(claimScreenPermissionPrompt({ ...p, status: 'not-determined' })).toBe(false)
  expect(claimScreenPermissionPrompt({ ...p, status: 'granted' })).toBe(false)
  expect(claimScreenPermissionPrompt({ ...p, status: 'granted' })).toBe(false)
  expect(claimScreenPermissionPrompt(p)).toBe(true)
})
it('uses persisted reminder state without treating it as a permission grant', () => {
  const p = { appName: 'App', appId: 'persisted-app', status: 'denied' }
  window.localStorage.setItem('cua-screen-permission-notice:v1:persisted-app', 'shown')
  expect(claimScreenPermissionPrompt(p)).toBe(false)
  expect(claimScreenPermissionPrompt({ ...p, appId: 'new-install' })).toBe(true)
})
it('does not prompt on unsupported or unrecognized detection results', () => {
  expect(claimScreenPermissionPrompt({ appName: 'App', status: 'unsupported' })).toBe(false)
  expect(claimScreenPermissionPrompt({ appName: 'App', status: 'unknown' })).toBe(false)
})

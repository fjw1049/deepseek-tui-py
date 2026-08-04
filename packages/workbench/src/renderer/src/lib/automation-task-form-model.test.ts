import { describe, expect, it } from 'vitest'
import {
  buildAutomationSchedulePayload,
  buildCreateAutomationInput,
  deriveAutomationName
} from './automation-task-form-model'

describe('automation task form model', () => {
  it('builds hourly schedules anchored to the hour', () => {
    expect(
      buildAutomationSchedulePayload({
        kind: 'hourly',
        everyHours: '3',
        onceAt: '',
        timeOfDay: '',
        weekdays: [],
        customCron: ''
      })
    ).toEqual({ schedule: '0 */3 * * *' })
  })

  it('collapses an every-1-hour schedule to the plain hourly form', () => {
    expect(
      buildAutomationSchedulePayload({
        kind: 'hourly',
        everyHours: '1',
        onceAt: '',
        timeOfDay: '',
        weekdays: [],
        customCron: ''
      })
    ).toEqual({ schedule: '0 * * * *' })
  })

  it('rejects hourly intervals that cron cannot express', () => {
    expect(() =>
      buildAutomationSchedulePayload({
        kind: 'hourly',
        everyHours: '48',
        onceAt: '',
        timeOfDay: '',
        weekdays: [],
        customCron: ''
      })
    ).toThrow('interval_invalid')
  })

  it('builds daily schedules with a wildcard day-of-week', () => {
    expect(
      buildAutomationSchedulePayload({
        kind: 'daily',
        everyHours: '',
        onceAt: '',
        timeOfDay: '09:30',
        weekdays: [],
        customCron: ''
      })
    ).toEqual({ schedule: '30 9 * * *' })
  })

  it('builds one-time schedules as a run_at with no cron', () => {
    const payload = buildAutomationSchedulePayload({
      kind: 'once',
      onceAt: '2026-06-01T10:00',
      everyHours: '',
      timeOfDay: '',
      weekdays: [],
      customCron: ''
    })

    expect(payload.schedule).toBeNull()
    expect(payload.run_at).toMatch(/^2026-06-01T/)
  })

  it('rejects custom expressions that are not 5 fields', () => {
    expect(() =>
      buildAutomationSchedulePayload({
        kind: 'custom',
        onceAt: '',
        everyHours: '',
        timeOfDay: '',
        weekdays: [],
        customCron: '0 9 * *'
      })
    ).toThrow('cron_invalid')
  })

  it('builds create payloads with derived names, workspace, status, and delivery', () => {
    const payload = buildCreateAutomationInput({
      name: '',
      prompt: 'Summarize the workspace\nwith details',
      workspaceRoot: '/tmp/project',
      schedule: {
        kind: 'weekly',
        onceAt: '',
        everyHours: '',
        timeOfDay: '18:05',
        weekdays: ['MON', 'FRI'],
        customCron: ''
      },
      deliveryMode: 'email',
      deliveryTarget: 'me@example.com',
      createPaused: true
    })

    expect(payload).toMatchObject({
      name: 'Summarize the workspace',
      prompt: 'Summarize the workspace\nwith details',
      schedule: '5 18 * * MON,FRI',
      cwds: ['/tmp/project'],
      status: 'paused',
      delivery: { mode: 'email', to: 'me@example.com', best_effort: false }
    })
    expect(payload.timezone).toBeTruthy()
  })

  it('uses channel defaults when delivery target is blank', () => {
    const payload = buildCreateAutomationInput({
      name: 'Daily report',
      prompt: 'Check disk usage',
      workspaceRoot: '/tmp',
      schedule: {
        kind: 'daily',
        onceAt: '',
        everyHours: '',
        timeOfDay: '08:00',
        weekdays: [],
        customCron: ''
      },
      deliveryMode: 'email',
      deliveryTarget: '',
      channelDefaults: { email: 'me@example.com' },
      createPaused: false
    })

    expect(payload.delivery).toEqual({
      mode: 'email',
      to: 'me@example.com',
      best_effort: false
    })
  })

  it('truncates derived names', () => {
    expect(deriveAutomationName('a'.repeat(60))).toBe(`${'a'.repeat(45)}...`)
  })
})

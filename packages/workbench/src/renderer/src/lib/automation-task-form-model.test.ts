import { describe, expect, it } from 'vitest'
import {
  buildAutomationSchedulePayload,
  buildCreateAutomationInput,
  deriveAutomationName
} from './automation-task-form-model'

describe('automation task form model', () => {
  it('builds hourly schedules', () => {
    expect(
      buildAutomationSchedulePayload({
        kind: 'hourly',
        everyHours: '3',
        onceAt: '',
        timeOfDay: '',
        weekdays: [],
        customRrule: ''
      })
    ).toEqual({ rrule: 'FREQ=HOURLY;INTERVAL=3' })
  })

  it('builds daily schedules as all-week weekly RRULEs', () => {
    expect(
      buildAutomationSchedulePayload({
        kind: 'daily',
        everyHours: '',
        onceAt: '',
        timeOfDay: '09:30',
        weekdays: [],
        customRrule: ''
      })
    ).toEqual({
      rrule: 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR,SA,SU;BYHOUR=9;BYMINUTE=30'
    })
  })

  it('builds one-time schedules with next_run_at', () => {
    const payload = buildAutomationSchedulePayload({
      kind: 'once',
      onceAt: '2026-06-01T10:00',
      everyHours: '',
      timeOfDay: '',
      weekdays: [],
      customRrule: ''
    })

    expect(payload.rrule).toBe('FREQ=HOURLY;INTERVAL=8760')
    expect(payload.next_run_at).toMatch(/^2026-06-01T/)
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
        weekdays: ['MO', 'FR'],
        customRrule: ''
      },
      deliveryMode: 'email',
      deliveryTarget: 'me@example.com',
      createPaused: true
    })

    expect(payload).toMatchObject({
      name: 'Summarize the workspace',
      prompt: 'Summarize the workspace\nwith details',
      rrule: 'FREQ=WEEKLY;BYDAY=MO,FR;BYHOUR=18;BYMINUTE=5',
      cwds: ['/tmp/project'],
      status: 'paused',
      delivery: { mode: 'email', to: 'me@example.com', best_effort: true }
    })
  })

  it('truncates derived names', () => {
    expect(deriveAutomationName('a'.repeat(60))).toBe(`${'a'.repeat(45)}...`)
  })
})

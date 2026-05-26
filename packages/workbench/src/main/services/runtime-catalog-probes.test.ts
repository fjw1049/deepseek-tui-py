import { describe, expect, it } from 'vitest'
import {
  parseSessionsProbe,
  parseSkillsProbe,
  parseTasksProbe
} from './runtime-catalog-probes'

describe('runtime-catalog-probes', () => {
  it('parses skills count and warnings', () => {
    const probe = parseSkillsProbe({
      ok: true,
      status: 200,
      body: JSON.stringify({
        skills: [{ name: 'a' }, { name: 'b' }],
        warnings: ['warn']
      })
    })
    expect(probe.ok).toBe(true)
    expect(probe.count).toBe(2)
    expect(probe.warningCount).toBe(1)
  })

  it('marks tasks as disabled on 503', () => {
    const probe = parseTasksProbe({
      ok: false,
      status: 503,
      body: '{"detail":{"message":"task manager not configured"}}'
    })
    expect(probe.ok).toBe(false)
    expect(probe.status).toBe(503)
    expect(probe.message).toContain('not configured')
  })

  it('parses sessions tui and linked counts', () => {
    const probe = parseSessionsProbe({
      ok: true,
      status: 200,
      body: JSON.stringify({
        sessions: [
          { kind: 'tui', import_state: 'available' },
          { kind: 'tui', import_state: 'linked' },
          { kind: 'thread', import_state: 'native' }
        ]
      })
    })
    expect(probe.count).toBe(2)
    expect(probe.warningCount).toBe(1)
  })
})

import { describe, expect, it } from 'vitest'
import { parseAutomationIntent, parseAutomationSchedule, parseTimeOfDay } from './parse-automation-intent'

describe('parseTimeOfDay', () => {
  it('parses chinese 十点', () => {
    expect(parseTimeOfDay('每天十点发邮件')).toBe('10:00')
  })
  it('parses 10:30', () => {
    expect(parseTimeOfDay('每天 10:30 推送')).toBe('10:30')
  })
})

describe('parseAutomationSchedule', () => {
  it('daily at ten', () => {
    const s = parseAutomationSchedule('每天十点把小米股票的发给我')
    expect(s?.kind).toBe('daily')
    expect(s?.timeOfDay).toBe('10:00')
    expect(s?.rrule).toContain('BYHOUR=10')
    expect(s?.rrule).toContain('BYMINUTE=0')
  })

  it('weekly monday', () => {
    const s = parseAutomationSchedule('每周一 9:00 发简报')
    expect(s?.kind).toBe('weekly')
    expect(s?.rrule).toContain('BYDAY=MO')
  })
})

describe('parseAutomationIntent', () => {
  it('parses xiaomi daily example', () => {
    const r = parseAutomationIntent('每天十点把小米股票的发给我呢')
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(r.intent.schedule.label).toContain('每天')
    expect(r.intent.agentPrompt).toContain('小米')
    expect(r.intent.deliveryMode).toBe('email')
  })

  it('detects feishu delivery', () => {
    const r = parseAutomationIntent('每天十点把小米股票发到飞书')
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(r.intent.deliveryMode).toBe('feishu')
  })
})

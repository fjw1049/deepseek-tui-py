/**
 * Bridge Claw GUI schedule types ↔ backend AutomationManager RRULE subset.
 *
 * @see docs/AUTOMATION_FRAMEWORK.md — Claw GUI tasks persist as AutomationRecord,
 * not a second scheduler.
 */

import type { ClawTaskScheduleV1 } from './app-settings'
import type { ParsedAutomationSchedule } from './parse-automation-intent'

/** Map parsed NL schedule → Claw settings schedule (for electron-store UI). */
export function parsedScheduleToClaw(schedule: ParsedAutomationSchedule): ClawTaskScheduleV1 {
  if (schedule.kind === 'hourly') {
    return {
      kind: 'interval',
      everyMinutes: Math.max(1, schedule.intervalHours * 60),
      timeOfDay: schedule.timeOfDay,
      atTime: ''
    }
  }
  if (schedule.kind === 'weekly') {
    return {
      kind: 'daily',
      everyMinutes: 60,
      timeOfDay: schedule.timeOfDay,
      atTime: ''
    }
  }
  return {
    kind: 'daily',
    everyMinutes: 60,
    timeOfDay: schedule.timeOfDay,
    atTime: ''
  }
}

export function clawScheduleLabel(schedule: ClawTaskScheduleV1, rrule: string): string {
  if (schedule.kind === 'interval') {
    return schedule.everyMinutes === 60 ? '每小时' : `每 ${schedule.everyMinutes} 分钟`
  }
  if (schedule.kind === 'at' && schedule.atTime) {
    return `一次性 · ${schedule.atTime}`
  }
  if (schedule.kind === 'daily') {
    if (/BYDAY=MO,TU,WE,TH,FR,SA,SU/.test(rrule)) {
      return `每天 ${schedule.timeOfDay}`
    }
    const m = rrule.match(/BYDAY=([A-Z,]+)/)
    if (m) return `每周 ${schedule.timeOfDay}`
    return `每天 ${schedule.timeOfDay}`
  }
  return '手动'
}

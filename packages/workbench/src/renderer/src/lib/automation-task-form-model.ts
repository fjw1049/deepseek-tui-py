import type { AutomationStatus, CreateAutomationInput } from './automation-runtime-client'

export type AutomationScheduleKind = 'once' | 'hourly' | 'daily' | 'weekly' | 'custom'
export type AutomationDeliveryMode = 'none' | 'feishu' | 'email'
export type WeekdayToken = 'MO' | 'TU' | 'WE' | 'TH' | 'FR' | 'SA' | 'SU'

export const ALL_WEEKDAYS: WeekdayToken[] = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']

export type AutomationScheduleDraft = {
  kind: AutomationScheduleKind
  onceAt: string
  everyHours: string
  timeOfDay: string
  weekdays: WeekdayToken[]
  customRrule: string
}

export type AutomationTaskDraft = {
  name: string
  prompt: string
  workspaceRoot: string
  schedule: AutomationScheduleDraft
  deliveryMode: AutomationDeliveryMode
  deliveryTarget: string
  /** Fallback targets from channel center when deliveryTarget is blank. */
  channelDefaults?: { feishu?: string; email?: string }
  createPaused: boolean
}

export type AutomationSchedulePayload = {
  rrule: string
  next_run_at?: string | null
}

function parseTimeOfDay(value: string): { hour: number; minute: number } {
  const match = value.trim().match(/^(\d{1,2}):(\d{2})$/)
  if (!match) throw new Error('time_of_day_invalid')
  const hour = Number(match[1])
  const minute = Number(match[2])
  if (!Number.isInteger(hour) || hour < 0 || hour > 23) throw new Error('time_of_day_invalid')
  if (!Number.isInteger(minute) || minute < 0 || minute > 59) throw new Error('time_of_day_invalid')
  return { hour, minute }
}

export function deriveAutomationName(prompt: string): string {
  const firstLine = prompt.trim().split(/\r?\n/)[0]?.trim() ?? ''
  if (!firstLine) return 'Scheduled automation'
  return firstLine.length > 48 ? `${firstLine.slice(0, 45)}...` : firstLine
}

export function buildAutomationSchedulePayload(
  schedule: AutomationScheduleDraft
): AutomationSchedulePayload {
  if (schedule.kind === 'once') {
    const date = new Date(schedule.onceAt)
    if (!schedule.onceAt || Number.isNaN(date.getTime())) throw new Error('once_at_invalid')
    return {
      rrule: 'FREQ=HOURLY;INTERVAL=8760',
      next_run_at: date.toISOString()
    }
  }

  if (schedule.kind === 'hourly') {
    const interval = Number(schedule.everyHours)
    if (!Number.isInteger(interval) || interval < 1) throw new Error('interval_invalid')
    return { rrule: `FREQ=HOURLY;INTERVAL=${interval}` }
  }

  if (schedule.kind === 'daily') {
    const { hour, minute } = parseTimeOfDay(schedule.timeOfDay)
    return {
      rrule: `FREQ=WEEKLY;BYDAY=${ALL_WEEKDAYS.join(',')};BYHOUR=${hour};BYMINUTE=${minute}`
    }
  }

  if (schedule.kind === 'weekly') {
    const { hour, minute } = parseTimeOfDay(schedule.timeOfDay)
    const weekdays = schedule.weekdays.filter((day) => ALL_WEEKDAYS.includes(day))
    if (weekdays.length === 0) throw new Error('weekdays_required')
    return {
      rrule: `FREQ=WEEKLY;BYDAY=${weekdays.join(',')};BYHOUR=${hour};BYMINUTE=${minute}`
    }
  }

  const rrule = schedule.customRrule.trim().toUpperCase()
  if (!rrule) throw new Error('rrule_required')
  return { rrule }
}

export function resolveEffectiveDeliveryTarget(draft: AutomationTaskDraft): string {
  const explicit = draft.deliveryTarget.trim()
  if (explicit) return explicit
  if (draft.deliveryMode === 'feishu') return draft.channelDefaults?.feishu?.trim() ?? ''
  if (draft.deliveryMode === 'email') return draft.channelDefaults?.email?.trim() ?? ''
  return ''
}

export function buildCreateAutomationInput(draft: AutomationTaskDraft): CreateAutomationInput {
  const prompt = draft.prompt.trim()
  if (!prompt) throw new Error('prompt_required')

  const schedule = buildAutomationSchedulePayload(draft.schedule)
  const workspaceRoot = draft.workspaceRoot.trim()
  const status: AutomationStatus = draft.createPaused ? 'paused' : 'active'
  const effectiveTarget = resolveEffectiveDeliveryTarget(draft)

  return {
    name: draft.name.trim() || deriveAutomationName(prompt),
    prompt,
    rrule: schedule.rrule,
    next_run_at: schedule.next_run_at,
    cwds: workspaceRoot ? [workspaceRoot] : [],
    status,
    delivery:
      draft.deliveryMode === 'none' || !effectiveTarget
        ? undefined
        : {
            mode: draft.deliveryMode,
            to: effectiveTarget,
            best_effort: true
          }
  }
}

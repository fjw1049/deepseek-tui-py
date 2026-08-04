/** Runtime API client for durable automations (`/v1/automations`). */

export type AutomationStatus = 'active' | 'paused' | 'completed'

export type AutomationRecord = {
  id: string
  name: string
  prompt: string
  /** 5-field cron expression, or null for a one-shot job. */
  schedule: string | null
  /** IANA timezone the schedule is evaluated in. */
  timezone: string
  status: AutomationStatus | string
  created_at?: string
  updated_at?: string
  cwds?: string[]
  next_run_at?: string | null
  last_run_at?: string | null
  delivery?: { mode?: string; to?: string; best_effort?: boolean }
  digest?: Record<string, unknown>
}

export type CreateAutomationInput = {
  name: string
  prompt: string
  /** Omit for a one-shot job; then run_at is required. */
  schedule?: string | null
  timezone?: string
  run_at?: string | null
  cwds?: string[]
  status?: AutomationStatus
  delivery?: { mode: string; to?: string; best_effort?: boolean }
}

export type UpdateAutomationInput = Omit<Partial<CreateAutomationInput>, 'delivery'> & {
  delivery?: CreateAutomationInput['delivery'] | Record<string, never>
}

export type AutomationRunRecord = {
  id: string
  automation_id: string
  scheduled_for: string
  status: string
  created_at: string
  started_at?: string | null
  ended_at?: string | null
  task_id?: string | null
  thread_id?: string | null
  turn_id?: string | null
  error?: string | null
  delivery_done?: boolean
}

async function runtimeJson<T>(path: string, method: string, body?: unknown): Promise<T> {
  const raw = await window.dsGui.runtimeRequest(
    path,
    method,
    body === undefined ? undefined : JSON.stringify(body)
  )
  if (!raw.ok) {
    let message = `HTTP ${raw.status}`
    try {
      const parsed = JSON.parse(raw.body) as { detail?: string; error?: string; message?: string }
      message = parsed.detail ?? parsed.message ?? parsed.error ?? message
    } catch {
      if (raw.body.trim()) message = raw.body.trim().slice(0, 240)
    }
    throw new Error(message)
  }
  if (!raw.body.trim()) {
    return undefined as T
  }
  return JSON.parse(raw.body) as T
}

export function automationIdFromClawTask(lastMessage: string): string | null {
  const m = lastMessage.trim().match(/^automation:([a-f0-9]+)$/i)
  return m?.[1] ?? null
}

const CRON_WEEKDAY_ZH: Record<string, string> = {
  '0': '日',
  '1': '一',
  '2': '二',
  '3': '三',
  '4': '四',
  '5': '五',
  '6': '六',
  '7': '日',
  SUN: '日',
  MON: '一',
  TUE: '二',
  WED: '三',
  THU: '四',
  FRI: '五',
  SAT: '六'
}

/**
 * Human-readable label for a cron schedule.
 *
 * Covers the shapes the form produces; anything hand-written falls back to
 * the raw expression, which is itself readable for cron users.
 */
export function formatAutomationSchedule(schedule: string | null | undefined): string {
  if (!schedule) return '仅一次'
  const fields = schedule.trim().split(/\s+/)
  if (fields.length !== 5) return schedule
  const [minute, hour, dom, month, dow] = fields
  if (dom !== '*' || month !== '*') return schedule

  const everyNHours = hour.match(/^\*\/(\d+)$/)
  if (minute === '0' && everyNHours) return `每 ${everyNHours[1]} 小时`
  if (minute === '0' && hour === '*' && dow === '*') return '每小时'

  if (!/^\d+$/.test(minute) || !/^\d+$/.test(hour)) return schedule
  const time = `${hour.padStart(2, '0')}:${minute.padStart(2, '0')}`
  if (dow === '*') return `每天 ${time}`

  const days = dow.split(',').map((d) => CRON_WEEKDAY_ZH[d.toUpperCase()])
  if (days.some((d) => d === undefined)) return schedule
  return `每周${days.join('、')} ${time}`
}

export function formatAutomationWhen(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

export async function listAutomations(): Promise<AutomationRecord[]> {
  const rows = await runtimeJson<AutomationRecord[]>('/v1/automations', 'GET')
  return Array.isArray(rows) ? rows : []
}

export async function createAutomation(input: CreateAutomationInput): Promise<AutomationRecord> {
  return runtimeJson<AutomationRecord>('/v1/automations', 'POST', input)
}

export async function getAutomation(id: string): Promise<AutomationRecord> {
  return runtimeJson<AutomationRecord>(`/v1/automations/${encodeURIComponent(id)}`, 'GET')
}

export async function updateAutomation(
  id: string,
  input: UpdateAutomationInput
): Promise<AutomationRecord> {
  return runtimeJson<AutomationRecord>(`/v1/automations/${encodeURIComponent(id)}`, 'PATCH', input)
}

export async function pauseAutomation(id: string): Promise<AutomationRecord> {
  return runtimeJson<AutomationRecord>(`/v1/automations/${encodeURIComponent(id)}/pause`, 'POST', {})
}

export async function resumeAutomation(id: string): Promise<AutomationRecord> {
  return runtimeJson<AutomationRecord>(`/v1/automations/${encodeURIComponent(id)}/resume`, 'POST', {})
}

export async function deleteAutomation(id: string): Promise<AutomationRecord> {
  return runtimeJson<AutomationRecord>(`/v1/automations/${encodeURIComponent(id)}`, 'DELETE')
}

export async function runAutomationNow(id: string): Promise<{ id: string; status: string; task_id?: string }> {
  return runtimeJson(`/v1/automations/${encodeURIComponent(id)}/run`, 'POST', {})
}

export async function listAutomationRuns(
  id: string,
  limit = 50
): Promise<AutomationRunRecord[]> {
  const rows = await runtimeJson<AutomationRunRecord[]>(
    `/v1/automations/${encodeURIComponent(id)}/runs?limit=${limit}`,
    'GET'
  )
  return Array.isArray(rows) ? rows : []
}

/** Runtime API client for durable automations (`/v1/automations`). */

export type AutomationStatus = 'active' | 'paused'

export type AutomationRecord = {
  id: string
  name: string
  prompt: string
  rrule: string
  status: AutomationStatus | string
  next_run_at?: string | null
  last_run_at?: string | null
  delivery?: { mode?: string; to?: string; best_effort?: boolean }
}

export type CreateAutomationInput = {
  name: string
  prompt: string
  rrule: string
  cwds?: string[]
  status?: AutomationStatus
  delivery?: { mode: string; to: string; best_effort?: boolean }
  next_run_at?: string | null
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

/** Human-readable schedule from backend RRULE subset. */
export function formatAutomationRrule(rrule: string): string {
  const parts = Object.fromEntries(
    rrule.split(';').map((seg) => {
      const [k, v] = seg.split('=')
      return [k?.trim().toUpperCase() ?? '', v?.trim() ?? '']
    })
  )
  const freq = parts.FREQ ?? ''
  if (freq === 'HOURLY') {
    const n = Number(parts.INTERVAL || '1')
    return n <= 1 ? '每小时' : `每 ${n} 小时`
  }
  if (freq === 'WEEKLY') {
    const h = parts.BYHOUR ?? '0'
    const m = parts.BYMINUTE ?? '0'
    const time = `${h.padStart(2, '0')}:${m.padStart(2, '0')}`
    const days = parts.BYDAY ?? ''
    if (days.split(',').length >= 7) {
      return `每天 ${time}`
    }
    const map: Record<string, string> = {
      MO: '一',
      TU: '二',
      WE: '三',
      TH: '四',
      FR: '五',
      SA: '六',
      SU: '日'
    }
    const zh = days
      .split(',')
      .map((d) => map[d] ?? d)
      .join('、')
    return `每周${zh} ${time}`
  }
  return rrule
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

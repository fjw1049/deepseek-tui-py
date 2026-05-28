/**
 * Composer「自动化」→ Claw task mirror (settings) + durable AutomationRecord (runtime API).
 */

import type { ClawTaskFromTextResult, ClawTaskV1 } from '@shared/app-settings'
import { clawScheduleLabel, parsedScheduleToClaw } from '@shared/claw-schedule-bridge'
import { parseAutomationIntent } from '@shared/parse-automation-intent'
import { resolveAutomationFeishuChatId } from './resolve-automation-feishu-chat-id'
import { resolveAutomationMailTo } from './resolve-automation-mail-to'

type AutomationWire = {
  id: string
  name: string
  next_run_at?: string | null
}

async function runtimePost<T>(path: string, body: unknown): Promise<T> {
  const raw = await window.dsGui.runtimeRequest(path, 'POST', JSON.stringify(body))
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
  return JSON.parse(raw.body) as T
}

function newClawTaskId(): string {
  return `claw-${Date.now().toString(36)}`
}

/**
 * Natural language → backend automation + Claw settings task row (for future Claw tab).
 * Matches `ClawTaskFromTextResult` in app-settings.ts.
 */
export async function createClawTaskFromText(
  text: string,
  options: { workspaceRoot: string }
): Promise<ClawTaskFromTextResult> {
  const trimmed = text.trim()
  if (!trimmed) return { kind: 'noop' }

  const parsed = parseAutomationIntent(trimmed)
  if (!parsed.ok) {
    return { kind: 'error', message: parsed.error }
  }

  const { intent } = parsed
  const settings = await window.dsGui.getSettings()
  const feishuTo =
    (await resolveAutomationFeishuChatId()) ??
    settings.claw?.im?.feishuReceiveId?.trim() ??
    ''

  let delivery: { mode: string; to: string; best_effort?: boolean }
  let deliveryLabel: string
  if (intent.deliveryMode === 'feishu') {
    if (!feishuTo) {
      return {
        kind: 'error',
        message:
          '未配置飞书接收人。请在 设置 → Claw → 飞书 填写 chat_id，保存到 config.toml 的 [automation]。'
      }
    }
    delivery = { mode: 'feishu', to: feishuTo, best_effort: true }
    deliveryLabel = `飞书 ${feishuTo}`
  } else {
    const mailTo = await resolveAutomationMailTo()
    if (!mailTo) {
      return {
        kind: 'error',
        message:
          '未配置收件邮箱。请在 ~/.deepseek/config.toml 的 [automation] 下设置 mail_to。'
      }
    }
    delivery = { mode: 'email', to: mailTo, best_effort: true }
    deliveryLabel = mailTo
  }
  const schedule = parsedScheduleToClaw(intent.schedule)
  const workspace = options.workspaceRoot.trim()

  let automation: AutomationWire
  try {
    automation = await runtimePost<AutomationWire>('/v1/automations', {
      name: intent.name,
      prompt: intent.agentPrompt,
      rrule: intent.schedule.rrule,
      status: 'active',
      cwds: workspace ? [workspace] : [],
      delivery
    })
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    return { kind: 'error', message }
  }

  const now = new Date().toISOString()
  const clawTask: ClawTaskV1 = {
    id: newClawTaskId(),
    title: intent.name,
    enabled: true,
    prompt: trimmed,
    workspaceRoot: workspace,
    model: 'auto',
    mode: 'agent',
    schedule,
    createdAt: now,
    updatedAt: now,
    lastRunAt: '',
    nextRunAt: automation.next_run_at ?? '',
    lastStatus: 'idle',
    lastMessage: `automation:${automation.id}`,
    lastThreadId: ''
  }

  try {
    const settings = await window.dsGui.getSettings()
    const tasks = [...(settings.claw?.tasks ?? []), clawTask]
    await window.dsGui.setSettings({
      claw: {
        enabled: true,
        tasks
      }
    })
  } catch {
    /* settings mirror is best-effort; backend automation is source of truth */
  }

  const scheduleAt =
    automation.next_run_at != null
      ? new Date(automation.next_run_at).toLocaleString()
      : clawScheduleLabel(schedule, intent.schedule.rrule)

  return {
    kind: 'created',
    taskId: clawTask.id,
    title: intent.name,
    scheduleAt,
    confirmationText: `已创建自动化「${intent.name}」：${intent.schedule.label}，结果将发到 ${deliveryLabel}。下次运行：${scheduleAt}`
  }
}

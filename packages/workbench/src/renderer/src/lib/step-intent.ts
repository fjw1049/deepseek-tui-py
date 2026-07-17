import {
  describeToolCallTarget,
  humanizeToolName
} from '../components/chat/tool/render-context'

export type StepIntent = {
  /** Humanized tool name, e.g. "读取文件". */
  title: string
  /** Primary target/query, e.g. "…/StepFlow.tsx". */
  detail: string
  /** Compact one-liner for previews: `title  detail`. */
  label: string
}

function parseInputRecord(raw: string | null | undefined): Record<string, unknown> {
  if (!raw?.trim()) return {}
  try {
    const parsed: unknown = JSON.parse(raw.trim())
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>
    }
  } catch {
    // Not JSON — fall through to free-form primaryArg handling.
  }
  return {}
}

function compactFreeformArg(arg: string): string {
  const oneLine = arg.replace(/\s+/g, ' ').trim()
  if (!oneLine) return ''
  // Path-like: keep the meaningful tail so truncation never hides the file.
  if (/[\\/]/.test(oneLine) && !/\s/.test(oneLine)) {
    const clean = oneLine.replace(/\\/g, '/').replace(/\/+$/, '')
    const segments = clean.split('/').filter(Boolean)
    if (segments.length > 2) return `…/${segments.slice(-2).join('/')}`
    return clean
  }
  if (oneLine.length <= 72) return oneLine
  return `${oneLine.slice(0, 71).trimEnd()}…`
}

/**
 * Build the step-rail "what is this doing" copy from a tool name plus either
 * mailbox `input_summary` JSON or a task-timeline primary arg.
 */
export function buildStepIntent(opts: {
  toolName: string
  inputSummary?: string | null
  primaryArg?: string | null
}): StepIntent {
  const toolName = (opts.toolName || 'tool').trim() || 'tool'
  const title = humanizeToolName(toolName) || toolName
  const args = parseInputRecord(opts.inputSummary)

  let detail = describeToolCallTarget(toolName, args)

  // Non-JSON input_summary (rare): treat the whole string as the target.
  if (!detail && opts.inputSummary?.trim() && Object.keys(args).length === 0) {
    detail = compactFreeformArg(opts.inputSummary.trim())
  }

  if (!detail && opts.primaryArg?.trim()) {
    // Task timeline already extracted `name · arg`; prefer describing via a
    // synthetic summary so path/query heuristics still apply.
    detail =
      describeToolCallTarget(toolName, {}, {
        summary: `${toolName}: ${opts.primaryArg.trim()}`,
        filePath: opts.primaryArg.trim()
      }) || compactFreeformArg(opts.primaryArg.trim())
  }

  const label = detail ? `${title}  ${detail}` : title
  return { title, detail, label }
}

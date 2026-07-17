import type { StepFlowItem } from '../components/chat/StepFlow'

const SHELL_TOOLS = new Set([
  'exec_shell',
  'exec_shell_wait',
  'exec_shell_interact',
  'run_terminal_cmd'
])

const MUTATING_TOOLS = new Set([
  'write_file',
  'edit_file',
  'apply_patch',
  'delete_file'
])

const ORCHESTRATION_TOOL_RE =
  /^(?:agent_spawn|spawn_agent|delegate_to_agent|agent_wait|wait|agent_result|agent_list|agent_cancel)$/i

const PROBE_TOOLS = new Set([
  'read_file',
  'list_dir',
  'grep',
  'grep_files',
  'search_files',
  'glob_file_search',
  'file_search',
  'web_search',
  'fetch_url'
])

/** Read-only probes that the main timeline folds into tool batches. */
export function isMergeableProbeTool(name: string | undefined): boolean {
  if (!name) return false
  const n = name.trim().toLowerCase()
  if (!n) return false
  if (SHELL_TOOLS.has(n) || MUTATING_TOOLS.has(n)) return false
  if (ORCHESTRATION_TOOL_RE.test(n)) return false
  return PROBE_TOOLS.has(n)
}

function isMergeableProbeItem(item: StepFlowItem): boolean {
  if (item.variant === 'narration' || item.variant === 'batch') return false
  if (item.status !== 'ok') return false
  return isMergeableProbeTool(item.toolName)
}

/**
 * Fold runs of ≥2 consecutive same-name successful probes into one batch row.
 * Narration / lifecycle / failed / running rows flush the buffer (same as
 * main-chat `groupProcessRows`).
 */
export function collapseStepFlowProbes(items: StepFlowItem[]): StepFlowItem[] {
  if (items.length < 2) return items

  const out: StepFlowItem[] = []
  let buffer: StepFlowItem[] = []
  let bufferName = ''

  const flush = (): void => {
    if (buffer.length >= 2) {
      const first = buffer[0]!
      const paths = buffer
        .map((i) => i.detail?.trim() || i.label.trim())
        .filter(Boolean)
      out.push({
        id: `batch-${first.id}`,
        status: 'ok',
        label: first.label,
        depth: first.depth,
        variant: 'batch',
        toolName: bufferName,
        batchToolName: bufferName,
        batchCount: buffer.length,
        output: paths.length > 0 ? paths.join('\n') : null
      })
    } else if (buffer.length === 1) {
      out.push(buffer[0]!)
    }
    buffer = []
    bufferName = ''
  }

  for (const item of items) {
    if (isMergeableProbeItem(item) && item.toolName) {
      const name = item.toolName.trim().toLowerCase()
      if (buffer.length > 0 && name !== bufferName) flush()
      bufferName = name
      buffer.push(item)
      continue
    }
    flush()
    out.push(item)
  }
  flush()
  return out
}

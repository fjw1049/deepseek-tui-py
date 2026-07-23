import type { StepFlowItem, StepFlowStatus } from '../components/chat/StepFlow'

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

/**
 * Settled + live probes may fold. Queued/pending stay individual so the rail
 * does not imply work that has not started.
 */
const MERGEABLE_STATUSES = new Set<StepFlowStatus>([
  'ok',
  'failed',
  'cancelled',
  'completed',
  'info',
  'skipped',
  'running'
])

export type ProbeBatchKind = 'read' | 'search' | 'list' | 'grep' | 'web' | 'other'

export type ProbeBatchCompose = {
  reads: number
  searches: number
  lists: number
  greps: number
  webs: number
  others: number
}

export type ProbeBatchEntry = {
  toolName: string
  kind: ProbeBatchKind
  target: string
}

/** i18n key fragment for compose segments (toolBatchComposeRead, …). */
export type ProbeComposeSegmentKey =
  | 'toolBatchComposeRead'
  | 'toolBatchComposeSearch'
  | 'toolBatchComposeList'
  | 'toolBatchComposeGrep'
  | 'toolBatchComposeWeb'
  | 'toolBatchComposeOther'

/** i18n key for short kind labels in expanded batch rows. */
export type ProbeKindLabelKey =
  | 'toolBatchKindRead'
  | 'toolBatchKindSearch'
  | 'toolBatchKindList'
  | 'toolBatchKindGrep'
  | 'toolBatchKindWeb'
  | 'toolBatchKindOther'

/** Read-only probes that the main timeline folds into tool batches. */
export function isMergeableProbeTool(name: string | undefined): boolean {
  if (!name) return false
  const n = name.trim().toLowerCase()
  if (!n) return false
  if (SHELL_TOOLS.has(n) || MUTATING_TOOLS.has(n)) return false
  if (ORCHESTRATION_TOOL_RE.test(n)) return false
  return PROBE_TOOLS.has(n)
}

export function probeToolKind(toolName: string | undefined): ProbeBatchKind {
  const n = (toolName || '').trim().toLowerCase()
  if (n === 'read_file') return 'read'
  if (n === 'list_dir') return 'list'
  if (n === 'grep' || n === 'grep_files') return 'grep'
  if (n === 'search_files' || n === 'glob_file_search' || n === 'file_search') return 'search'
  if (n === 'web_search' || n === 'fetch_url') return 'web'
  return 'other'
}

export function emptyProbeCompose(): ProbeBatchCompose {
  return { reads: 0, searches: 0, lists: 0, greps: 0, webs: 0, others: 0 }
}

export function addProbeCompose(compose: ProbeBatchCompose, kind: ProbeBatchKind): void {
  if (kind === 'read') compose.reads += 1
  else if (kind === 'search') compose.searches += 1
  else if (kind === 'list') compose.lists += 1
  else if (kind === 'grep') compose.greps += 1
  else if (kind === 'web') compose.webs += 1
  else compose.others += 1
}

/** Ordered non-zero compose segments for i18n title assembly. */
export function probeComposeSegments(
  compose: ProbeBatchCompose
): Array<{ key: ProbeComposeSegmentKey; count: number }> {
  const out: Array<{ key: ProbeComposeSegmentKey; count: number }> = []
  if (compose.reads > 0) out.push({ key: 'toolBatchComposeRead', count: compose.reads })
  if (compose.searches > 0) out.push({ key: 'toolBatchComposeSearch', count: compose.searches })
  if (compose.lists > 0) out.push({ key: 'toolBatchComposeList', count: compose.lists })
  if (compose.greps > 0) out.push({ key: 'toolBatchComposeGrep', count: compose.greps })
  if (compose.webs > 0) out.push({ key: 'toolBatchComposeWeb', count: compose.webs })
  if (compose.others > 0) out.push({ key: 'toolBatchComposeOther', count: compose.others })
  return out
}

export function probeKindLabelKey(kind: ProbeBatchKind): ProbeKindLabelKey {
  switch (kind) {
    case 'read':
      return 'toolBatchKindRead'
    case 'search':
      return 'toolBatchKindSearch'
    case 'list':
      return 'toolBatchKindList'
    case 'grep':
      return 'toolBatchKindGrep'
    case 'web':
      return 'toolBatchKindWeb'
    default:
      return 'toolBatchKindOther'
  }
}

export function buildProbeBatchMeta(
  items: Array<{ toolName?: string; detail?: string; label?: string }>
): { compose: ProbeBatchCompose; entries: ProbeBatchEntry[]; preview: string } {
  const compose = emptyProbeCompose()
  const entries: ProbeBatchEntry[] = []
  for (const item of items) {
    const toolName = (item.toolName || '').trim()
    const kind = probeToolKind(toolName)
    addProbeCompose(compose, kind)
    // Only the real target/query — never fall back to the humanized tool title
    // in `label` (e.g. "读取文件"), or the preview becomes meaningless noise.
    const target = item.detail?.trim() || ''
    entries.push({ toolName, kind, target })
  }
  const preview = entries
    .map((e) => e.target)
    .filter(Boolean)
    .join(' · ')
  return { compose, entries, preview }
}

function isMergeableProbeItem(item: StepFlowItem): boolean {
  if (item.variant === 'narration' || item.variant === 'batch') return false
  if (!MERGEABLE_STATUSES.has(item.status)) return false
  return isMergeableProbeTool(item.toolName)
}

function isSuccessStatus(status: StepFlowStatus): boolean {
  return status === 'ok' || status === 'completed'
}

/**
 * Aggregate batch chrome status. Partial cancel (residual unfinished rows on an
 * interrupted card) must not paint a mostly-successful streak as cancelled.
 */
export function batchStatus(items: StepFlowItem[]): StepFlowStatus {
  if (items.some((i) => i.status === 'running')) return 'running'
  if (items.some((i) => i.status === 'failed')) return 'failed'
  const anyOk = items.some((i) => isSuccessStatus(i.status))
  const anyCancelled = items.some((i) => i.status === 'cancelled')
  if (anyCancelled && !anyOk) return 'cancelled'
  if (anyOk) return 'ok'
  return 'info'
}

/**
 * Fold runs of ≥2 consecutive probes into one batch row.
 * Same-name runs keep that tool label; mixed read/search/grep runs carry
 * compose counts (`batchCompose`) for a “读 2 · 搜 2” title. Narration /
 * lifecycle / queued rows flush the buffer.
 */
export function collapseStepFlowProbes(items: StepFlowItem[]): StepFlowItem[] {
  if (items.length < 2) return items

  const out: StepFlowItem[] = []
  let buffer: StepFlowItem[] = []

  const flush = (): void => {
    if (buffer.length >= 2) {
      const first = buffer[0]!
      const names = new Set(
        buffer.map((i) => (i.toolName || '').trim().toLowerCase()).filter(Boolean)
      )
      const mixed = names.size > 1
      const bufferName = mixed ? 'probe' : [...names][0] || first.toolName || 'probe'
      const { compose, entries, preview } = buildProbeBatchMeta(buffer)
      out.push({
        id: `batch-${first.id}`,
        status: batchStatus(buffer),
        label: first.label,
        depth: first.depth,
        variant: 'batch',
        toolName: bufferName,
        batchToolName: bufferName,
        batchCount: buffer.length,
        batchMixed: mixed,
        batchCompose: compose,
        batchEntries: entries,
        detail: preview || undefined,
        output: preview || null
      })
    } else if (buffer.length === 1) {
      out.push(buffer[0]!)
    }
    buffer = []
  }

  for (const item of items) {
    if (isMergeableProbeItem(item) && item.toolName) {
      buffer.push(item)
      continue
    }
    flush()
    out.push(item)
  }
  flush()
  return out
}

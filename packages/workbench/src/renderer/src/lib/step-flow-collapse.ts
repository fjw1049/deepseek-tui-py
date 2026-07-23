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

const COMPOSE_KIND_ORDER: Array<{
  kind: ProbeBatchKind
  key: ProbeComposeSegmentKey
  countKey: keyof ProbeBatchCompose
}> = [
  { kind: 'read', key: 'toolBatchComposeRead', countKey: 'reads' },
  { kind: 'search', key: 'toolBatchComposeSearch', countKey: 'searches' },
  { kind: 'list', key: 'toolBatchComposeList', countKey: 'lists' },
  { kind: 'grep', key: 'toolBatchComposeGrep', countKey: 'greps' },
  { kind: 'web', key: 'toolBatchComposeWeb', countKey: 'webs' },
  { kind: 'other', key: 'toolBatchComposeOther', countKey: 'others' }
]

/** Ordered non-zero compose segments for i18n title assembly. */
export function probeComposeSegments(
  compose: ProbeBatchCompose
): Array<{ key: ProbeComposeSegmentKey; count: number }> {
  const out: Array<{ key: ProbeComposeSegmentKey; count: number }> = []
  for (const { key, countKey } of COMPOSE_KIND_ORDER) {
    const count = compose[countKey]
    if (count > 0) out.push({ key, count })
  }
  return out
}

export type ProbeComposeTitleSegment = {
  key: ProbeComposeSegmentKey
  /** True when the segment names a real path/query instead of a count. */
  concrete: boolean
  /** Concrete path/query when `concrete`; otherwise unused. */
  target: string
  count: number
}

/**
 * Title segments for *mixed* probe batches.
 * - kind count === 1 and a concrete target exists → “读 plan.py”
 * - kind count > 1 (or no target) → “读 2 项”
 * Same-tool batches do not use this.
 */
export function probeComposeTitleSegments(
  entries: ProbeBatchEntry[],
  compose?: ProbeBatchCompose
): ProbeComposeTitleSegment[] {
  const grouped = new Map<ProbeBatchKind, string[]>()
  for (const entry of entries) {
    const target = entry.target.trim()
    if (!target) continue
    const list = grouped.get(entry.kind) ?? []
    list.push(target)
    grouped.set(entry.kind, list)
  }
  const out: ProbeComposeTitleSegment[] = []
  for (const { kind, key, countKey } of COMPOSE_KIND_ORDER) {
    const targets = grouped.get(kind) ?? []
    const count = compose?.[countKey] ?? (targets.length > 0 ? targets.length : 0)
    if (count <= 0) continue
    if (count === 1 && targets.length === 1) {
      out.push({ key, concrete: true, target: targets[0]!, count })
    } else {
      out.push({ key, concrete: false, target: '', count })
    }
  }
  return out
}

/** True when every mixed-title segment is a concrete target (no count leftovers). */
export function probeComposeTitleIsFullyConcrete(
  segments: ProbeComposeTitleSegment[]
): boolean {
  return segments.length > 0 && segments.every((seg) => seg.concrete)
}

/** Render one mixed-batch title segment via i18n (target form vs “N 项” count). */
export function formatProbeComposeTitleSegment(
  seg: ProbeComposeTitleSegment,
  t: (key: string, opts?: Record<string, unknown>) => string
): string {
  return seg.concrete
    ? t(seg.key, { target: seg.target })
    : t(`${seg.key}Count`, { count: seg.count })
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
 * Same-name runs keep that tool label (“读取文件 · N 项”); mixed
 * read/search/grep runs carry compose + entries for a target-first title
 * (“读 a.py · 搜 foo”). Narration / lifecycle / queued rows flush the buffer.
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

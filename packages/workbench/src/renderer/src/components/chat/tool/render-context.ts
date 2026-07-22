import type { ToolBlock } from '../../../agent/types'
import {
  countDiffStats,
  looksLikeUnifiedDiff,
  type DiffStats
} from '../../../lib/diff-stats'
import { parseUnifiedDiffForEditor } from '../../../lib/parse-unified-diff-for-editor'

/**
 * The lifecycle state of a tool call, as the renderer sees it. Mapped from
 * `ToolBlock.status` — deepseek's runtime never surfaces an approval state
 * on a tool block (approvals are their own `ChatBlock` kind), so this is a
 * trimmed-down set compared to a full agent UI.
 */
export type ToolUIState = 'running' | 'success' | 'error'

export interface ToolRenderContext {
  /** Raw tool name extracted from the summary, e.g. "read_file". */
  toolName: string
  /** Tool name with any namespace prefix stripped (here equal to toolName). */
  shortName: string
  /** Humanized label, e.g. "读取文件". */
  label: string
  /** One-line descriptor built from input, e.g. "src/foo.ts". */
  description: string
  state: ToolUIState
  toolCallId: string
  /** Parsed input fields surfaced for the header/output renderers. */
  input: ToolInput
  /** Raw detail text (stdout/stderr or unified patch). */
  output?: string
  /** True when `output` was truncated and full text is lazy-loadable. */
  outputTruncated?: boolean
  /** Error text when state === 'error'. */
  errorText?: string
  /** Whether this tool is a file mutation (drives diff rendering). */
  isFileChange: boolean
  /** Whether this tool is a command execution (drives terminal rendering). */
  isCommand: boolean
  /** +N/-N for file mutations (exact runtime counts preferred, else parsed). */
  diffStats?: DiffStats
  /** First changed line in the new file (1-based), for "open at line" jumps. */
  editLine?: number
  /** Structured metadata from the runtime (exit_code, duration_ms, command…). */
  meta?: Record<string, unknown>
}

export interface ToolInput {
  path?: string
  pattern?: string
  command?: string
}

/**
 * Build a render context from a `ToolBlock`. Centralises the messy extraction
 * of tool name / label / input descriptor so every renderer sees the same
 * normalised shape — the registry resolves purely off `ctx`.
 */
export function buildToolRenderContext(block: ToolBlock): ToolRenderContext {
  const toolName = extractToolName(block.summary)
  const shortName = stripToolPrefix(toolName)
  const isFileChange = block.toolKind === 'file_change'
  // Shell-detected edits arrive as file_change blocks under a non-edit tool
  // name (e.g. exec_shell); render them with the edit label, not "执行命令".
  const label =
    isFileChange && !FILE_EDIT_TOOL_NAMES.has(toolName.trim().toLowerCase())
      ? TOOL_NAME_LABELS.edit_file
      : humanizeToolName(toolName)
  const description = buildDescription(block, toolName)
  const input = extractInput(block)
  const state = mapState(block)
  const isCommand = block.toolKind === 'command_execution'
  const mutation = readMutationMeta(block.meta)
  const diffStats = isFileChange ? resolveDiffStats(block, mutation) : undefined
  const editLine = isFileChange ? resolveEditLine(block, mutation) : undefined

  return {
    toolName,
    shortName,
    label,
    description,
    state,
    toolCallId: block.id,
    input,
    ...(block.detail !== undefined && block.detail.trim()
      ? { output: block.detail }
      : {}),
    ...(block.detailTruncated ? { outputTruncated: true } : {}),
    ...(state === 'error' && block.detail ? { errorText: block.detail } : {}),
    isFileChange,
    isCommand,
    ...(diffStats ? { diffStats } : {}),
    ...(editLine !== undefined ? { editLine } : {}),
    ...(block.meta ? { meta: block.meta } : {})
  }
}

export function isPendingState(state: ToolUIState): boolean {
  return state === 'running'
}

export function isResolvedState(state: ToolUIState): boolean {
  return state === 'success' || state === 'error'
}

function mapState(block: ToolBlock): ToolUIState {
  if (block.status === 'running') return 'running'
  if (block.status === 'error') return 'error'
  return 'success'
}

// ── extraction helpers (ported from MessageTimeline, now owned by the tool layer) ──

const TOOL_NAME_LABELS: Record<string, string> = {
  agent_cancel: '取消子代理',
  agent_list: '子代理列表',
  agent_result: '获取子代理结果',
  agent_spawn: '派生子代理',
  agent_wait: '等待子代理',
  apply_patch: '应用补丁',
  delegate_to_agent: '委派子代理',
  edit_file: '编辑文件',
  exec_shell: '执行命令',
  exec_shell_interact: '交互命令',
  exec_shell_wait: '等待命令',
  fetch_url: '获取网页',
  file_search: '搜索文件',
  github_issue_context: '读取 GitHub 上下文',
  glob_file_search: '搜索文件',
  grep: '搜索代码',
  grep_files: '搜索文件',
  list_dir: '浏览目录',
  read_file: '读取文件',
  run_terminal_cmd: '执行命令',
  search_files: '搜索文件',
  spawn_agent: '派生子代理',
  web_search: '网络搜索',
  write_file: '写入文件'
}

/** Tools whose own label already describes a file edit (others fall back). */
const FILE_EDIT_TOOL_NAMES = new Set(['edit_file', 'write_file', 'apply_patch'])

export function humanizeToolName(name: string): string {
  const canonical = name.trim().toLowerCase()
  const mapped = TOOL_NAME_LABELS[canonical]
  if (mapped) return mapped
  const trimmed = canonical.replace(/[_-]+/g, ' ')
  if (!trimmed) return ''
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1)
}

export function extractToolName(summary: string): string {
  const match = summary.trim().match(/^([a-z0-9_-]+)\s*:/i)
  return match?.[1] ?? ''
}

export function stripToolPrefix(name: string): string {
  const segments = name.split('__')
  return segments[segments.length - 1] || name
}

// Common argument names across deepseek/cursor/codex tool schemas. The runtime
// forwards the raw call args under `meta.tool_input`; we probe these in priority
// order so every tool row can show *what* it acted on, not just its name.
type ToolInputRecord = Record<string, unknown>
const PATH_KEYS = ['path', 'file_path', 'file', 'target_file', 'filename', 'abs_path', 'absolute_path']
const DIR_KEYS = ['directory', 'dir', 'target_directory', 'path_to_directory', 'dir_path', 'relative_workspace_path']
const PATTERN_KEYS = ['pattern', 'query', 'search', 'regex', 'search_term']
const GLOB_KEYS = ['glob', 'glob_pattern', 'include_pattern', 'includeGlob', 'include', 'globs']
const CMD_KEYS = ['command', 'cmd', 'script']
const URL_KEYS = ['url', 'uri', 'link']

function collectToolInput(block: ToolBlock): ToolInputRecord {
  const raw = block.meta?.tool_input
  return raw && typeof raw === 'object' && !Array.isArray(raw) ? (raw as ToolInputRecord) : {}
}

function firstString(input: ToolInputRecord, keys: string[]): string | undefined {
  for (const key of keys) {
    const value = input[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
    if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  }
  return undefined
}

function firstAnyString(input: ToolInputRecord): string | undefined {
  for (const value of Object.values(input)) {
    if (typeof value === 'string' && value.trim() && value.length <= 200) return value.trim()
  }
  return undefined
}

/** Show the meaningful tail of a path so end-truncation never hides the file. */
function compactPath(path: string): string {
  const clean = path.replace(/\\/g, '/').replace(/\/+$/, '')
  const segments = clean.split('/').filter(Boolean)
  if (segments.length <= 2) return clean
  return `…/${segments.slice(-2).join('/')}`
}

/**
 * One-line "what this tool acted on" descriptor from raw call args.
 * Shared by ToolCard and step-rail intent labels.
 */
export function describeToolCallTarget(
  toolName: string,
  input: ToolInputRecord = {},
  extras?: {
    filePath?: string
    summary?: string
    detail?: string
    meta?: Record<string, unknown>
    toolKind?: ToolBlock['toolKind']
  }
): string {
  const sourceText = [extras?.summary?.trim() ?? '', extras?.detail ?? '']
    .filter(Boolean)
    .join('\n')

  const path =
    firstString(input, PATH_KEYS) ||
    extras?.filePath ||
    extractQuotedField(sourceText, 'path') ||
    extractQuotedField(sourceText, 'file_path') ||
    extractQuotedField(sourceText, 'file')
  const dir = firstString(input, DIR_KEYS)
  const pattern =
    firstString(input, PATTERN_KEYS) ||
    extractQuotedField(sourceText, 'pattern') ||
    extractQuotedField(sourceText, 'query') ||
    readMetaString(extras?.meta, 'pattern')
  const glob = firstString(input, GLOB_KEYS)
  const command = firstString(input, CMD_KEYS) || readMetaString(extras?.meta, 'command')
  const url = firstString(input, URL_KEYS)

  if (extras?.toolKind === 'command_execution' && command) {
    return summarizeProcessText(command, 72)
  }
  if (toolName === 'list_dir') {
    const target = dir || path
    return target ? compactPath(target) : ''
  }
  if (toolName === 'grep' || toolName === 'grep_files' || toolName === 'search_files') {
    const where = dir || path
    if (pattern || glob) {
      const query = (pattern || glob)!
      return where ? `${query} · ${compactPath(where)}` : query
    }
    return where ? compactPath(where) : ''
  }
  if (toolName === 'glob_file_search' || toolName === 'file_search') {
    const query = glob || pattern
    return query || (path ? compactPath(path) : '')
  }
  if (toolName === 'fetch_url' || url) return url || ''
  if (toolName === 'web_search') return pattern || ''
  if (path) return compactPath(path)
  if (pattern || glob) return (pattern || glob)!
  if (command) return summarizeProcessText(command, 72)

  const generic = firstAnyString(input)
  if (generic) return summarizeProcessText(generic, 72)

  // Last resort: whatever follows the "tool_name:" prefix in the summary.
  const rawSummary = extras?.summary?.trim() ?? ''
  if (rawSummary && rawSummary.toLowerCase() !== toolName) {
    const withoutPrefix = toolName
      ? rawSummary.replace(/^([a-z0-9_-]+)\s*:\s*/i, '')
      : rawSummary
    return summarizeProcessText(stripInlineJsonPayload(withoutPrefix), 72)
  }
  return ''
}

function buildDescription(block: ToolBlock, toolName: string): string {
  return describeToolCallTarget(toolName, collectToolInput(block), {
    filePath: block.filePath,
    summary: block.summary,
    detail: block.detail,
    meta: block.meta,
    toolKind: block.toolKind
  })
}

function extractInput(block: ToolBlock): ToolInput {
  const inputArgs = collectToolInput(block)
  const sourceText = [block.summary ?? '', block.detail ?? ''].filter(Boolean).join('\n')
  const path =
    firstString(inputArgs, PATH_KEYS) ||
    block.filePath ||
    extractQuotedField(sourceText, 'path') ||
    extractQuotedField(sourceText, 'file_path') ||
    extractQuotedField(sourceText, 'file')
  const pattern =
    firstString(inputArgs, [...PATTERN_KEYS, ...GLOB_KEYS]) ||
    extractQuotedField(sourceText, 'pattern') ||
    extractQuotedField(sourceText, 'query') ||
    readMetaString(block.meta, 'pattern')
  const command = firstString(inputArgs, CMD_KEYS) || readMetaString(block.meta, 'command')
  const input: ToolInput = {}
  if (path) input.path = path
  if (pattern) input.pattern = pattern
  if (command) input.command = command
  return input
}

function extractQuotedField(text: string, field: string): string | undefined {
  const escaped = field.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const attr = new RegExp(`${escaped}="([^"]+)"`, 'i').exec(text)
  if (attr?.[1]) return attr[1]
  const json = new RegExp(`"${escaped}"\\s*:\\s*"([^"]+)"`, 'i').exec(text)
  if (json?.[1]) return json[1]
  return undefined
}

function readMetaString(
  meta: Record<string, unknown> | undefined,
  key: string
): string | undefined {
  if (!meta) return undefined
  const value = meta[key]
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

/** Structured file-mutation payload (`meta.mutation`) when the runtime sends it. */
function readMutationMeta(
  meta: Record<string, unknown> | undefined
): Record<string, unknown> | undefined {
  const raw = meta?.mutation
  return raw && typeof raw === 'object' && !Array.isArray(raw)
    ? (raw as Record<string, unknown>)
    : undefined
}

function readMutationNumber(
  mutation: Record<string, unknown> | undefined,
  key: string
): number | undefined {
  const value = mutation?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

/** Exact +N/-N from the runtime when present; otherwise counted from the patch. */
function resolveDiffStats(
  block: ToolBlock,
  mutation: Record<string, unknown> | undefined
): DiffStats | undefined {
  const added = readMutationNumber(mutation, 'additions')
  const removed = readMutationNumber(mutation, 'deletions')
  if (added !== undefined || removed !== undefined) {
    const stats = { added: Math.max(0, added ?? 0), removed: Math.max(0, removed ?? 0) }
    return stats.added > 0 || stats.removed > 0 ? stats : undefined
  }
  return countDiffStats(block.detail) ?? undefined
}

/** First changed line in the NEW file: runtime hint, else parsed from the patch. */
function resolveEditLine(
  block: ToolBlock,
  mutation: Record<string, unknown> | undefined
): number | undefined {
  const fromMeta = readMutationNumber(mutation, 'line_start')
  if (fromMeta !== undefined && fromMeta >= 1) return Math.floor(fromMeta)
  const detail = block.detail
  if (!detail || !looksLikeUnifiedDiff(detail)) return undefined
  return parseUnifiedDiffForEditor(detail).addedLines[0]
}

function summarizeProcessText(text: string, max = 96): string {
  const oneLine = text.replace(/\s+/g, ' ').trim()
  if (!oneLine) return ''
  if (oneLine.length <= max) return oneLine
  return `${oneLine.slice(0, max - 1).trimEnd()}…`
}

function stripInlineJsonPayload(text: string): string {
  const match = text.match(/\s*[[{]\s*["{[]/)
  if (match && match.index !== undefined) {
    return text.slice(0, match.index).trim()
  }
  return text.trim()
}

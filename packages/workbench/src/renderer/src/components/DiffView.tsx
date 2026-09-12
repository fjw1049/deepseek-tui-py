import { useLayoutEffect, useMemo, useRef, useState, type ReactElement } from 'react'
import { Check, ChevronDown, ChevronUp, Minimize2, Columns2, Copy, MessageSquarePlus, Rows3 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { countDiffStats, extractDiffFilePath } from '../lib/diff-stats'
import { FileChip } from './chat/FileChip'
import { FileKindIcon } from './chat/FileKindIcon'
import { Tooltip } from './common/Tooltip'

export type DiffRenderStyle = 'unified' | 'split'

type Props = {
  patch: string
  className?: string
  /** Maximum visible height (px). Defaults to 320. Use >= 9000 to fill flex parent. */
  maxHeight?: number
  /** Optional file path; falls back to parsing from patch headers */
  filePath?: string
  /** Default unified (chat cards). Inspector review uses split. */
  diffStyle?: DiffRenderStyle
  showStyleToggle?: boolean
  onDiffStyleChange?: (style: DiffRenderStyle) => void
  /**
   * `card` — rounded inset card (chat tool previews).
   * `flush` — edge-to-edge in the change inspector (no padding card chrome).
   */
  chrome?: 'card' | 'flush'
  onAddToChat?: () => void
  /** Change inspector: replace copy with a control that collapses the diff pane. */
  onCollapse?: () => void
  onToggleExpand?: () => void
  expanded?: boolean
  /** Hide the file/stats header when a parent card already shows it. */
  showHeader?: boolean
  /** Keep the viewport pinned to the latest row (live file writes). */
  follow?: boolean
}

type ParsedDiff = {
  filePath: string | null
  added: number
  removed: number
}

type UnifiedRow = {
  key: number
  kind: 'meta' | 'context' | 'add' | 'del'
  oldNo: number | null
  newNo: number | null
  text: string
  cls: string
}

type SplitRow = {
  key: number
  kind: 'meta' | 'change'
  meta?: string
  leftNo: number | null
  rightNo: number | null
  leftText: string | null
  rightText: string | null
  leftKind: 'empty' | 'context' | 'del'
  rightKind: 'empty' | 'context' | 'add'
}

function parseDiff(patch: string, override?: string): ParsedDiff {
  const stats = countDiffStats(patch)
  return {
    filePath: extractDiffFilePath(patch, override) ?? null,
    added: stats?.added ?? 0,
    removed: stats?.removed ?? 0
  }
}

function filterBodyLines(lines: string[]): Array<{ line: string; i: number }> {
  return lines.map((line, i) => ({ line, i })).filter(({ line }) => {
    if (line.startsWith('--- ') || line.startsWith('+++ ')) return false
    if (line.startsWith('diff --git ')) return false
    if (line.startsWith('index ')) return false
    return true
  })
}

function buildUnifiedRows(bodyLines: Array<{ line: string; i: number }>): UnifiedRow[] {
  const rows: UnifiedRow[] = []
  let oldNo: number | null = null
  let newNo: number | null = null

  for (const { line, i } of bodyLines) {
    if (line.startsWith('@@')) {
      const m = line.match(/@@\s*-(\d+)(?:,\d+)?\s+\+(\d+)/)
      oldNo = m ? parseInt(m[1]!, 10) : null
      newNo = m ? parseInt(m[2]!, 10) : null
      rows.push({
        key: i,
        kind: 'meta',
        oldNo: null,
        newNo: null,
        text: line,
        cls: 'bg-accent-soft/60 text-ds-muted'
      })
      continue
    }
    if (line.startsWith('+')) {
      rows.push({
        key: i,
        kind: 'add',
        oldNo: null,
        newNo,
        text: line,
        cls: 'bg-ds-diff-added-soft text-ds-diff-added'
      })
      if (newNo != null) newNo += 1
      continue
    }
    if (line.startsWith('-')) {
      rows.push({
        key: i,
        kind: 'del',
        oldNo,
        newNo: null,
        text: line,
        cls: 'bg-ds-diff-removed-soft text-ds-diff-removed'
      })
      if (oldNo != null) oldNo += 1
      continue
    }
    rows.push({
      key: i,
      kind: 'context',
      oldNo,
      newNo,
      text: line,
      cls: 'text-ds-ink'
    })
    if (oldNo != null) oldNo += 1
    if (newNo != null) newNo += 1
  }
  return rows
}

function stripPrefix(line: string): string {
  if (line.startsWith('+') || line.startsWith('-') || line.startsWith(' ')) {
    return line.slice(1)
  }
  return line
}

/** A context run between hunks shorter than this stays fully visible. */
const CONTEXT_FOLD_THRESHOLD = 10
/** Keep a few context lines adjacent to each hunk when folding. */
const CONTEXT_FOLD_KEEP = 3

type UnifiedDisplayRow =
  | { type: 'row'; row: UnifiedRow }
  | { type: 'fold'; key: number; count: number; startKey: number }

/**
 * Collapse long context runs between hunks into an expandable separator
 * (GitHub/VS Code style). Leading/trailing context and short runs stay intact;
 * a run is only foldable when it sits between two hunk headers.
 */
function buildFoldedRows(rows: UnifiedRow[], unfolded: Set<number>): UnifiedDisplayRow[] {
  const out: UnifiedDisplayRow[] = []
  let i = 0
  let seenMeta = false
  while (i < rows.length) {
    const row = rows[i]!
    if (row.kind !== 'context') {
      if (row.kind === 'meta') seenMeta = true
      out.push({ type: 'row', row })
      i += 1
      continue
    }
    let j = i
    while (j < rows.length && rows[j]!.kind === 'context') j += 1
    const runLen = j - i
    const foldable =
      seenMeta && j < rows.length && runLen >= CONTEXT_FOLD_THRESHOLD && !unfolded.has(row.key)
    if (foldable) {
      const foldCount = runLen - CONTEXT_FOLD_KEEP * 2
      for (let k = 0; k < CONTEXT_FOLD_KEEP; k += 1) out.push({ type: 'row', row: rows[i + k]! })
      out.push({ type: 'fold', key: row.key, count: foldCount, startKey: rows[i + CONTEXT_FOLD_KEEP]!.key })
      for (let k = runLen - CONTEXT_FOLD_KEEP; k < runLen; k += 1) {
        out.push({ type: 'row', row: rows[i + k]! })
      }
    } else {
      for (let k = i; k < j; k += 1) out.push({ type: 'row', row: rows[k]! })
    }
    i = j
  }
  return out
}

function buildSplitRows(bodyLines: Array<{ line: string; i: number }>): SplitRow[] {
  const rows: SplitRow[] = []
  let oldNo: number | null = null
  let newNo: number | null = null
  let pendingDels: Array<{ i: number; text: string; no: number | null }> = []
  let keySeq = 0

  const flushDels = (): void => {
    for (const del of pendingDels) {
      rows.push({
        key: keySeq++,
        kind: 'change',
        leftNo: del.no,
        rightNo: null,
        leftText: del.text,
        rightText: null,
        leftKind: 'del',
        rightKind: 'empty'
      })
    }
    pendingDels = []
  }

  for (const { line, i } of bodyLines) {
    if (line.startsWith('@@')) {
      flushDels()
      const m = line.match(/@@\s*-(\d+)(?:,\d+)?\s+\+(\d+)/)
      oldNo = m ? parseInt(m[1]!, 10) : null
      newNo = m ? parseInt(m[2]!, 10) : null
      rows.push({ key: keySeq++, kind: 'meta', meta: line, leftNo: null, rightNo: null, leftText: null, rightText: null, leftKind: 'empty', rightKind: 'empty' })
      continue
    }
    if (line.startsWith('-')) {
      pendingDels.push({ i, text: stripPrefix(line), no: oldNo })
      if (oldNo != null) oldNo += 1
      continue
    }
    if (line.startsWith('+')) {
      const del = pendingDels.shift()
      rows.push({
        key: keySeq++,
        kind: 'change',
        leftNo: del?.no ?? null,
        rightNo: newNo,
        leftText: del?.text ?? null,
        rightText: stripPrefix(line),
        leftKind: del ? 'del' : 'empty',
        rightKind: 'add'
      })
      if (newNo != null) newNo += 1
      continue
    }
    flushDels()
    const text = stripPrefix(line)
    rows.push({
      key: keySeq++,
      kind: 'change',
      leftNo: oldNo,
      rightNo: newNo,
      leftText: text,
      rightText: text,
      leftKind: 'context',
      rightKind: 'context'
    })
    if (oldNo != null) oldNo += 1
    if (newNo != null) newNo += 1
  }
  flushDels()
  return rows
}

function sideCls(kind: 'empty' | 'context' | 'del' | 'add'): string {
  if (kind === 'del') return 'bg-ds-diff-removed-soft text-ds-diff-removed'
  if (kind === 'add') return 'bg-ds-diff-added-soft text-ds-diff-added'
  if (kind === 'empty') return 'bg-[color-mix(in_srgb,var(--ds-text)_3%,transparent)] text-ds-faint'
  return 'text-ds-ink'
}

/**
 * Lightweight diff renderer with dual gutters and optional side-by-side split.
 * Chat tool cards keep unified; the change inspector defaults to split.
 */
export function DiffView({
  patch,
  className = '',
  maxHeight = 320,
  filePath,
  diffStyle: controlledStyle,
  showStyleToggle = false,
  onDiffStyleChange,
  chrome = 'card',
  onAddToChat,
  onCollapse,
  onToggleExpand,
  expanded = false,
  showHeader = true,
  follow = false
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const looksLikePatch = useMemo(
    () => patch.split('\n').some((l) => /^[+-]/.test(l) || l.startsWith('@@')),
    [patch]
  )
  const parsed = useMemo(() => parseDiff(patch, filePath), [patch, filePath])
  const [copied, setCopied] = useState(false)
  const [localStyle, setLocalStyle] = useState<DiffRenderStyle>(controlledStyle ?? 'unified')
  const diffStyle = controlledStyle ?? localStyle

  const fileLabel = parsed.filePath ?? filePath ?? null
  const displayName = fileLabel ? fileLabel.split(/[/\\]/).pop() ?? fileLabel : null
  const fillParent = maxHeight >= 9000

  const bodyLines = useMemo(() => filterBodyLines(patch.split('\n')), [patch])
  const unifiedRows = useMemo(() => buildUnifiedRows(bodyLines), [bodyLines])
  const splitRows = useMemo(() => buildSplitRows(bodyLines), [bodyLines])
  const [unfoldedContext, setUnfoldedContext] = useState<Set<number>>(new Set())
  const displayRows = useMemo(
    () => buildFoldedRows(unifiedRows, unfoldedContext),
    [unifiedRows, unfoldedContext]
  )
  const bodyRef = useRef<HTMLDivElement | HTMLPreElement>(null)

  useLayoutEffect(() => {
    if (!follow) return
    const viewport = bodyRef.current
    if (!viewport || viewport.scrollHeight <= viewport.clientHeight) return
    viewport.scrollTo({ top: viewport.scrollHeight, behavior: 'smooth' })
  }, [follow, patch])

  const setStyle = (next: DiffRenderStyle): void => {
    if (controlledStyle == null) setLocalStyle(next)
    onDiffStyleChange?.(next)
  }

  const onCopy = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(patch)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1400)
    } catch {
      /* clipboard unavailable */
    }
  }

  const flush = chrome === 'flush'
  const shellClass = flush
    ? `ds-diff-view ds-diff-view--flush flex h-full min-h-0 min-w-0 flex-col overflow-hidden ${className}`
    : `ds-diff-view ds-card-strong flex min-h-0 min-w-0 flex-col overflow-hidden rounded-[14px] ${className}`
  const bodyClass = `ds-change-inspector__code min-w-0 ${
    fillParent || flush ? 'min-h-0 flex-1 overflow-auto' : 'overflow-auto'
  }`
  /** Keep header inset and code gutters on the same 8px rhythm. */
  const gutterStyle = { width: flush ? 36 : 40 } as const
  const cellPad = 'px-2'

  const header = showHeader ? (
    <DiffHeader
      name={displayName}
      filePath={fileLabel}
      added={looksLikePatch ? parsed.added : null}
      removed={looksLikePatch ? parsed.removed : null}
      onCopy={onCopy}
      copied={copied}
      showStyleToggle={looksLikePatch && showStyleToggle}
      diffStyle={diffStyle}
      onDiffStyleChange={setStyle}
      flush={flush}
      onAddToChat={onAddToChat}
      onCollapse={onCollapse}
      onToggleExpand={onToggleExpand}
      expanded={expanded}
    />
  ) : null

  if (!looksLikePatch) {
    return (
      <div className={shellClass}>
        {header}
        <pre
          ref={bodyRef}
          className={`${bodyClass} whitespace-pre text-ds-ink ${flush ? 'px-2 py-1' : 'p-3'}`}
          style={fillParent || flush ? undefined : { maxHeight }}
        >
          {patch}
        </pre>
      </div>
    )
  }

  return (
    <div className={shellClass}>
      {header}
      <div ref={bodyRef} className={bodyClass} style={fillParent || flush ? undefined : { maxHeight }}>
        {diffStyle === 'split' ? (
          <table className="w-full table-fixed border-collapse">
            <colgroup>
              <col style={gutterStyle} />
              <col />
              <col style={gutterStyle} />
              <col />
            </colgroup>
            <tbody>
              {splitRows.map((row) => {
                if (row.kind === 'meta') {
                  return (
                    <tr key={row.key} className="bg-accent-soft/60 text-ds-muted">
                      <td colSpan={4} className="ds-diff-meta-sticky break-all px-2 py-0.5 font-mono text-[14px]">
                        {row.meta}
                      </td>
                    </tr>
                  )
                }
                return (
                  <tr key={row.key}>
                    <td
                      className={`select-none px-1 text-right align-top font-mono text-[13px] tabular-nums text-ds-faint ${sideCls(row.leftKind)}`}
                    >
                      {row.leftNo ?? ''}
                    </td>
                    <td
                      className={`max-w-0 break-all whitespace-pre-wrap ${cellPad} align-top font-mono text-[14.5px] leading-[1.45] ${sideCls(row.leftKind)}`}
                    >
                      {row.leftText ?? '\u00a0'}
                    </td>
                    <td
                      className={`select-none border-l border-ds-border-muted/50 px-1 text-right align-top font-mono text-[13px] tabular-nums text-ds-faint ${sideCls(row.rightKind)}`}
                    >
                      {row.rightNo ?? ''}
                    </td>
                    <td
                      className={`max-w-0 break-all whitespace-pre-wrap ${cellPad} align-top font-mono text-[14.5px] leading-[1.45] ${sideCls(row.rightKind)}`}
                    >
                      {row.rightText ?? '\u00a0'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        ) : (
          <table className="w-full table-fixed border-collapse">
            <colgroup>
              <col style={gutterStyle} />
              <col style={gutterStyle} />
              <col />
            </colgroup>
            <tbody>
              {displayRows.map((entry) => {
                if (entry.type === 'fold') {
                  return (
                    <tr key={`fold-${entry.key}`}>
                      <td colSpan={3} className="bg-[color-mix(in_srgb,var(--ds-text)_4%,transparent)] px-2 py-0.5">
                        <button
                          type="button"
                          onClick={() =>
                            setUnfoldedContext((prev) => {
                              const next = new Set(prev)
                              next.add(entry.key)
                              return next
                            })
                          }
                          className="font-mono text-[12.5px] text-ds-faint transition hover:text-ds-muted"
                          title={t('diffExpandContext')}
                        >
                          {'\u22ef '}
                          {t('diffUnmodifiedLines', { count: entry.count })}
                        </button>
                      </td>
                    </tr>
                  )
                }
                const row = entry.row
                if (row.kind === 'meta') {
                  return (
                    <tr key={row.key}>
                      <td className="ds-diff-meta-sticky select-none px-1 text-right align-top font-mono text-[13px]" />
                      <td className="ds-diff-meta-sticky select-none px-1 text-right align-top font-mono text-[13px]" />
                      <td className="ds-diff-meta-sticky max-w-0 truncate px-2 align-top font-mono text-[14px] text-ds-muted">
                        {row.text || '\u00a0'}
                      </td>
                    </tr>
                  )
                }
                return (
                  <tr key={row.key} className={row.cls}>
                    <td className="select-none px-1 text-right align-top font-mono text-[13px] tabular-nums text-ds-faint">
                      {row.oldNo ?? ''}
                    </td>
                    <td className="select-none border-r border-ds-border-muted/40 px-1 text-right align-top font-mono text-[13px] tabular-nums text-ds-faint">
                      {row.newNo ?? ''}
                    </td>
                    <td className="max-w-0 break-all whitespace-pre-wrap px-2 align-top font-mono text-[14.5px] leading-[1.45]">
                      {row.text || '\u00a0'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

/** GitHub-style two-segment bar; the green share encodes the added/removed ratio.
 *  Width comes from the caller via `className` (e.g. `w-12`). */
export function DiffStatBar({
  added,
  removed,
  className = 'w-12'
}: {
  added: number | null
  removed: number | null
  className?: string
}): ReactElement | null {
  if (added == null && removed == null) return null
  const a = added ?? 0
  const r = removed ?? 0
  if (a === 0 && r === 0) return null
  const addedPct = Math.round((a / (a + r)) * 100)
  return (
    <span
      className={`h-1 shrink-0 overflow-hidden rounded-full ${className}`.trim()}
      style={{
        background: `linear-gradient(to right, var(--ds-diff-added) 0%, var(--ds-diff-added) ${addedPct}%, var(--ds-diff-removed) ${addedPct}%, var(--ds-diff-removed) 100%)`
      }}
      aria-hidden
    />
  )
}

function DiffHeader({
  name,
  filePath,
  added,
  removed,
  onCopy,
  copied,
  showStyleToggle,
  diffStyle,
  onDiffStyleChange,
  flush = false,
  onAddToChat,
  onCollapse,
  onToggleExpand,
  expanded = false
}: {
  name: string | null
  filePath?: string | null
  added: number | null
  removed: number | null
  onCopy: () => void
  copied: boolean
  showStyleToggle: boolean
  diffStyle: DiffRenderStyle
  onDiffStyleChange: (style: DiffRenderStyle) => void
  flush?: boolean
  onAddToChat?: () => void
  onCollapse?: () => void
  onToggleExpand?: () => void
  expanded?: boolean
}): ReactElement {
  const { t } = useTranslation('common')
  return (
    <div
      className={
        flush
          ? 'ds-diff-view__header ds-change-inspector__pane-header flex shrink-0 items-center gap-2'
          : 'ds-diff-view__header flex h-9 shrink-0 items-center gap-2 border-b border-ds-border-muted px-3'
      }
    >
      {filePath ? null : (
        <FileKindIcon path={name ?? ''} className="ds-file-kind-icon--chrome" />
      )}
      {filePath ? (
        <FileChip
          path={filePath}
          label={name ?? undefined}
          variant="list"
          skipValidation
          className="min-w-0 flex-1 text-[14.5px] font-medium"
        />
      ) : (
        <span className="min-w-0 flex-1 truncate text-[14.5px] font-medium text-ds-ink" title={name ?? ''}>
          {name ?? 'patch'}
        </span>
      )}
      {added != null || removed != null ? (
        <>
          <span className="shrink-0 text-[14px] tabular-nums">
            {(added ?? 0) > 0 ? <span className="text-ds-diff-added">+{added}</span> : null}
            {(added ?? 0) > 0 && (removed ?? 0) > 0 ? <span className="px-1 text-ds-faint">·</span> : null}
            {(removed ?? 0) > 0 ? <span className="text-ds-diff-removed">-{removed}</span> : null}
          </span>
          <DiffStatBar added={added} removed={removed} />
        </>
      ) : null}
      {showStyleToggle ? (
        <div className="flex shrink-0 items-center rounded border border-ds-border-muted/70 p-0.5">
          <Tooltip label="Unified">
            <button
              type="button"
              onClick={() => onDiffStyleChange('unified')}
              className={`rounded px-1 py-0.5 transition ${
                diffStyle === 'unified' ? 'bg-ds-hover text-ds-ink' : 'text-ds-faint hover:text-ds-muted'
              }`}
              aria-label="Unified diff"
              aria-pressed={diffStyle === 'unified'}
            >
              <Rows3 className="h-3.5 w-3.5" strokeWidth={1.85} />
            </button>
          </Tooltip>
          <Tooltip label="Split">
            <button
              type="button"
              onClick={() => onDiffStyleChange('split')}
              className={`rounded px-1 py-0.5 transition ${
                diffStyle === 'split' ? 'bg-ds-hover text-ds-ink' : 'text-ds-faint hover:text-ds-muted'
              }`}
              aria-label="Split diff"
              aria-pressed={diffStyle === 'split'}
            >
              <Columns2 className="h-3.5 w-3.5" strokeWidth={1.85} />
            </button>
          </Tooltip>
        </div>
      ) : null}
      {onAddToChat ? (
        <Tooltip label={t('workspaceEditorAddToChat')}>
          <button
            type="button"
            onClick={onAddToChat}
            className="inline-flex h-7 w-7 items-center justify-center rounded text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
            aria-label={t('workspaceEditorAddToChat')}
          >
            <MessageSquarePlus className="h-3.5 w-3.5" strokeWidth={1.85} />
          </button>
        </Tooltip>
      ) : null}
      {onToggleExpand ? (
        <Tooltip label={t(expanded ? 'inspectorRestoreDiff' : 'inspectorExpandDiff')}>
          <button
            type="button"
            onClick={onToggleExpand}
            className="inline-flex h-7 w-7 items-center justify-center rounded text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink active:scale-[0.96]"
            aria-label={t(expanded ? 'inspectorRestoreDiff' : 'inspectorExpandDiff')}
            aria-pressed={expanded}
          >
            {expanded ? <Minimize2 className="h-3.5 w-3.5" strokeWidth={1.9} /> : <ChevronUp className="h-3.5 w-3.5" strokeWidth={1.9} />}
          </button>
        </Tooltip>
      ) : null}
      {onCollapse ? (
        <Tooltip label={t('inspectorCollapseDiff')}>
          <button
            type="button"
            onClick={onCollapse}
            className="inline-flex h-7 w-7 items-center justify-center rounded text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink active:scale-[0.96]"
            aria-label={t('inspectorCollapseDiff')}
          >
            <ChevronDown className="h-3.5 w-3.5" strokeWidth={1.9} />
          </button>
        </Tooltip>
      ) : (
        <Tooltip label="Copy diff">
          <button
            type="button"
            onClick={onCopy}
            className="inline-flex h-7 w-7 items-center justify-center rounded text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
            aria-label="Copy diff"
          >
            {copied ? (
              <Check className="h-3.5 w-3.5 text-ds-diff-added" strokeWidth={2} />
            ) : (
              <Copy className="h-3.5 w-3.5" strokeWidth={1.8} />
            )}
          </button>
        </Tooltip>
      )}
    </div>
  )
}

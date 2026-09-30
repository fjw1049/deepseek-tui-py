import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactElement } from 'react'
import { ArrowDown, ArrowUp, Check, ArrowDownToLine, ArrowUpToLine, Minimize2, Columns2, Copy, FileDiff, Loader2, Rows3, WrapText } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { countDiffStats, extractDiffFilePath } from '../lib/diff-stats'
import { FileChip } from './chat/FileChip'
import { FileKindIcon } from './chat/FileKindIcon'
import { Tooltip } from './common/Tooltip'
import { useCodeHighlights } from '../lib/use-code-highlights'
import { languageForPath } from '../lib/monaco-language-for-path'

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
  /** Change inspector: replace copy with a control that collapses the diff pane. */
  onCollapse?: () => void
  onToggleExpand?: () => void
  expanded?: boolean
  fullFilePatch?: string
  showFullFile?: boolean
  onToggleFullFile?: () => void
  fullFilePending?: boolean
  fullFileUnavailable?: boolean
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
  let inHunk = !lines.some((line) => line.startsWith('@@'))
  return lines.map((line, i) => ({ line, i })).filter(({ line }) => {
    if (line.startsWith('diff --git ')) inHunk = false
    if (line.startsWith('@@')) { inHunk = true; return true }
    // Patch metadata and the final newline are not source lines. In a hunk,
    // however, `--- text` and `+++ text` can be actual changed source.
    return inHunk && /^[ +-]/.test(line)
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
        cls: 'ds-diff-row-added text-ds-ink'
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
        cls: 'ds-diff-row-removed text-ds-ink'
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
  if (kind === 'del') return 'ds-diff-row-removed text-ds-ink'
  if (kind === 'add') return 'ds-diff-row-added text-ds-ink'
  if (kind === 'empty') return 'ds-diff-empty text-ds-faint'
  return 'text-ds-ink'
}

/** Preserve syntax token markup while marking the changed part of a paired line. */
export function highlightChangedText(text: string, html: string | undefined, counterpart?: string | null): string {
  const escaped = html ?? text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  if (counterpart === undefined || text === counterpart) return escaped || '&nbsp;'
  let start = 0
  let end = text.length
  if (counterpart !== null) {
    while (start < Math.min(text.length, counterpart.length) && text[start] === counterpart[start]) start++
    let otherEnd = counterpart.length
    while (end > start && otherEnd > start && text[end - 1] === counterpart[otherEnd - 1]) { end--; otherEnd-- }
  }
  if (start === end) return escaped || '&nbsp;'
  const doc = new DOMParser().parseFromString(`<span>${escaped}</span>`, 'text/html')
  const container = doc.body.firstElementChild!
  const walker = doc.createTreeWalker(container, 4 /* SHOW_TEXT */)
  const nodes: Text[] = []
  while (walker.nextNode()) nodes.push(walker.currentNode as Text)
  let offset = 0
  for (const node of nodes) {
    const value = node.data
    const from = Math.max(0, start - offset)
    const to = Math.min(value.length, end - offset)
    offset += value.length
    if (from >= to) continue
    const mark = doc.createElement('mark')
    mark.className = 'ds-diff-inline-change'
    mark.textContent = value.slice(from, to)
    node.replaceWith(doc.createTextNode(value.slice(0, from)), mark, doc.createTextNode(value.slice(to)))
  }
  return container.innerHTML
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
  onCollapse,
  onToggleExpand,
  expanded = false,
  fullFilePatch,
  showFullFile = false,
  onToggleFullFile,
  fullFilePending = false,
  fullFileUnavailable = false,
  showHeader = true,
  follow = false
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const fullContext = showFullFile && fullFilePatch !== undefined
  const visiblePatch = fullContext ? fullFilePatch : patch
  const looksLikePatch = useMemo(
    () => visiblePatch.split('\n').some((l) => /^[+-]/.test(l) || l.startsWith('@@')),
    [visiblePatch]
  )
  const parsed = useMemo(() => parseDiff(patch, filePath), [patch, filePath])
  const [copied, setCopied] = useState(false)
  const [localStyle, setLocalStyle] = useState<DiffRenderStyle>(controlledStyle ?? 'unified')
  const diffStyle = controlledStyle ?? localStyle
  const [wrapLines, setWrapLines] = useState(true)

  const fileLabel = parsed.filePath ?? filePath ?? null
  const displayName = fileLabel ? fileLabel.split(/[/\\]/).pop() ?? fileLabel : null
  const fillParent = maxHeight >= 9000

  const bodyLines = useMemo(() => filterBodyLines(visiblePatch.split('\n')), [visiblePatch])
  const unifiedRows = useMemo(() => buildUnifiedRows(bodyLines), [bodyLines])
  const oldSource = useMemo(() => unifiedRows.filter((row) => row.kind !== 'meta' && row.kind !== 'add'), [unifiedRows])
  const newSource = useMemo(() => unifiedRows.filter((row) => row.kind !== 'meta' && row.kind !== 'del'), [unifiedRows])
  const language = languageForPath(fileLabel ?? '')
  const oldHighlights = useCodeHighlights(oldSource.map((row) => stripPrefix(row.text)).join('\n'), language)
  const newHighlights = useCodeHighlights(newSource.map((row) => stripPrefix(row.text)).join('\n'), language)
  const oldTokens = new Map(oldSource.map((row, index) => [row.oldNo, oldHighlights?.[index]]))
  const newTokens = new Map(newSource.map((row, index) => [row.newNo, newHighlights?.[index]]))
  const codeLine = (text: string, html: string | undefined, counterpart?: string | null): ReactElement => {
    const content = highlightChangedText(text, html, counterpart)
    return <span className="ds-syntax-line" dangerouslySetInnerHTML={{ __html: content }} />
  }
  const splitRows = useMemo(() => buildSplitRows(bodyLines), [bodyLines])
  const oldPairs = new Map(splitRows.filter((row) => row.leftKind === 'del').map((row) => [row.leftNo, row.rightText]))
  const newPairs = new Map(splitRows.filter((row) => row.rightKind === 'add').map((row) => [row.rightNo, row.leftText]))
  const [unfoldedContext, setUnfoldedContext] = useState<Set<number>>(new Set())
  const displayRows = useMemo(
    () => fullContext ? unifiedRows.map((row): UnifiedDisplayRow => ({ type: 'row', row }))
      : buildFoldedRows(unifiedRows, unfoldedContext),
    [unifiedRows, unfoldedContext, fullContext]
  )
  useEffect(() => { setUnfoldedContext(new Set()) }, [visiblePatch, diffStyle])
  const splitDisplayRows = useMemo(() => {
    if (fullContext) return splitRows
    const result: Array<SplitRow | { kind: 'fold'; key: number; count: number }> = []
    for (let i = 0; i < splitRows.length;) {
      const row = splitRows[i]!
      let end = i
      while (end < splitRows.length && splitRows[end]!.leftKind === 'context') end++
      const length = end - i
      if (length >= CONTEXT_FOLD_THRESHOLD && !unfoldedContext.has(row.key)) {
        result.push(...splitRows.slice(i, i + CONTEXT_FOLD_KEEP))
        result.push({ kind: 'fold', key: row.key, count: length - CONTEXT_FOLD_KEEP * 2 })
        result.push(...splitRows.slice(end - CONTEXT_FOLD_KEEP, end))
        i = end
      } else if (length > 0) {
        result.push(...splitRows.slice(i, end))
        i = end
      } else {
        result.push(row)
        i++
      }
    }
    return result
  }, [splitRows, unfoldedContext, fullContext])
  const bodyRef = useRef<HTMLDivElement | HTMLPreElement>(null)

  useLayoutEffect(() => {
    if (!follow) return
    const viewport = bodyRef.current
    if (!viewport || viewport.scrollHeight <= viewport.clientHeight) return
    viewport.scrollTo({ top: viewport.scrollHeight, behavior: 'smooth' })
  }, [follow, patch])

  const [activeHunk, setActiveHunk] = useState(0)
  const unifiedHunks = new Set(unifiedRows.filter((row, index) => fullContext
    ? (row.kind === 'add' || row.kind === 'del') && !['add', 'del'].includes(unifiedRows[index - 1]?.kind ?? '')
    : row.kind === 'meta').map((row) => row.key))
  const splitHunks = new Set(splitRows.filter((row, index) => fullContext
    ? (row.leftKind === 'del' || row.rightKind === 'add') &&
      splitRows[index - 1]?.leftKind !== 'del' && splitRows[index - 1]?.rightKind !== 'add'
    : row.kind === 'meta').map((row) => row.key))
  const hunkCount = fullFilePending ? 0 : diffStyle === 'split' ? splitHunks.size : unifiedHunks.size
  useEffect(() => {
    setActiveHunk(0)
    if (!follow) bodyRef.current?.scrollTo?.({ top: 0, left: 0 })
  }, [visiblePatch, diffStyle, follow])
  const navigateHunk = (direction: number): void => {
    const hunks = bodyRef.current?.querySelectorAll<HTMLElement>('[data-diff-hunk]')
    if (!hunks?.length) return
    const next = (activeHunk + direction + hunks.length) % hunks.length
    hunks[next]?.scrollIntoView({ block: 'start' })
    setActiveHunk(next)
  }
  const expandContext = (key: number): void => {
    setUnfoldedContext((previous) => new Set([...previous, key]))
  }

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
      wrapLines={wrapLines}
      onToggleWrap={looksLikePatch ? () => setWrapLines((value) => !value) : undefined}
      flush={flush}
      navigation={looksLikePatch ? (
        <div className="ds-diff-navigation">
          <button type="button" disabled={!hunkCount} aria-label={t('diffPreviousChange')} title={t('diffPreviousChange')} onClick={() => navigateHunk(-1)}><ArrowUp size={17} strokeWidth={2.2} /></button>
          <button type="button" disabled={!hunkCount} aria-label={t('diffNextChange')} title={t('diffNextChange')} onClick={() => navigateHunk(1)}><ArrowDown size={17} strokeWidth={2.2} /></button>
        </div>
      ) : undefined}
      onCollapse={onCollapse}
      onToggleExpand={onToggleExpand}
      expanded={expanded}
      showFullFile={showFullFile}
      onToggleFullFile={onToggleFullFile}
    />
  ) : null

  if (fullFilePending) {
    return <div className={shellClass}>
      {header}
      <div role="status" className="flex min-h-0 flex-1 items-center justify-center gap-2 text-[13.5px] text-ds-faint">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />{t('diffLoadingFullFile')}
      </div>
    </div>
  }

  if (!looksLikePatch) {
    return (
      <div className={shellClass} data-wrap={wrapLines ? '' : undefined}>
        {header}
        <pre
          ref={(node) => { bodyRef.current = node }}
          className={`${bodyClass} whitespace-pre text-ds-ink ${flush ? 'px-2 py-1' : 'p-3'}`}
          style={fillParent || flush ? undefined : { maxHeight }}
        >
          {visiblePatch}
        </pre>
      </div>
    )
  }

  return (
    <div className={shellClass} data-wrap={wrapLines ? '' : undefined}>
      {header}
      {fullFileUnavailable ? <div role="status" className="shrink-0 px-2 py-1 text-[12.5px] text-ds-muted">
        {t('diffFullFileUnavailable')}
      </div> : null}
      <div ref={(node) => { bodyRef.current = node }} className={bodyClass} style={fillParent || flush ? undefined : { maxHeight }}>
        {diffStyle === 'split' ? (
          <table className="ds-diff-table border-collapse">
            <colgroup>
              <col style={gutterStyle} />
              <col />
              <col style={gutterStyle} />
              <col />
            </colgroup>
            <tbody>
              {splitDisplayRows.map((row) => {
                if (row.kind === 'fold') return (
                  <tr key={`fold-${row.key}`} className="ds-diff-fold"><td colSpan={4}>
                    <button type="button" onClick={() => expandContext(row.key)} title={t('diffExpandContext')}>
                      ⋯ {t('diffUnmodifiedLines', { count: row.count })}
                    </button>
                  </td></tr>
                )
                if (row.kind === 'meta') {
                  if (fullContext) return null
                  return (
                    <tr key={row.key} data-diff-hunk={splitHunks.has(row.key) ? '' : undefined} className="text-[color:var(--ds-diff-hunk)]">
                      <td colSpan={4} className="ds-diff-meta-sticky break-all px-2 py-0.5 font-mono text-[13.5px]">
                        {row.meta}
                      </td>
                    </tr>
                  )
                }
                return (
                  <tr key={row.key} data-diff-hunk={splitHunks.has(row.key) ? '' : undefined}>
                    <td
                      className={`select-none px-1 text-right align-top font-mono text-[12px] tabular-nums text-ds-faint ${sideCls(row.leftKind)}`}
                    >
                      {row.leftNo ?? ''}
                    </td>
                    <td
                      className={`ds-diff-code whitespace-pre ${cellPad} align-top font-mono text-[14px] leading-[23px] ${sideCls(row.leftKind)}`}
                    >
                      {codeLine(row.leftText ?? '', oldTokens.get(row.leftNo), row.leftKind === 'del' ? row.rightText : undefined)}
                    </td>
                    <td
                      className={`select-none border-l border-ds-border-muted/50 px-1 text-right align-top font-mono text-[12px] tabular-nums text-ds-faint ${sideCls(row.rightKind)}`}
                    >
                      {row.rightNo ?? ''}
                    </td>
                    <td
                      className={`ds-diff-code whitespace-pre ${cellPad} align-top font-mono text-[14px] leading-[23px] ${sideCls(row.rightKind)}`}
                    >
                      {codeLine(row.rightText ?? '', newTokens.get(row.rightNo), row.rightKind === 'add' ? row.leftText : undefined)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        ) : (
          <table className="ds-diff-table border-collapse">
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
                  if (fullContext) return null
                  return (
                    <tr key={row.key} data-diff-hunk={unifiedHunks.has(row.key) ? '' : undefined}>
                      <td className="ds-diff-meta-sticky select-none px-1 text-right align-top font-mono text-[13.5px]" />
                      <td className="ds-diff-meta-sticky select-none px-1 text-right align-top font-mono text-[13.5px]" />
                      <td className="ds-diff-meta-sticky max-w-0 truncate px-2 align-top font-mono text-[13.5px] text-[color:var(--ds-diff-hunk)]">
                        {row.text || '\u00a0'}
                      </td>
                    </tr>
                  )
                }
                return (
                  <tr key={row.key} data-diff-hunk={unifiedHunks.has(row.key) ? '' : undefined} className={row.cls}>
                    <td className="select-none px-1 text-right align-top font-mono text-[12px] tabular-nums text-ds-faint">
                      {row.oldNo ?? ''}
                    </td>
                    <td className="select-none border-r border-ds-border-muted/40 px-1 text-right align-top font-mono text-[12px] tabular-nums text-ds-faint">
                      {row.newNo ?? ''}
                    </td>
                    <td className="ds-diff-code whitespace-pre px-2 align-top font-mono text-[14px] leading-[23px]">
                      <span className={`ds-diff-sign ds-diff-sign--${row.kind}`} aria-hidden>{row.kind === 'add' ? '+' : row.kind === 'del' ? '−' : ' '}</span>
                      {codeLine(stripPrefix(row.text), row.kind === 'del' ? oldTokens.get(row.oldNo) : newTokens.get(row.newNo), row.kind === 'del' ? oldPairs.get(row.oldNo) : row.kind === 'add' ? newPairs.get(row.newNo) : undefined)}
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
  wrapLines,
  onToggleWrap,
  flush = false,
  navigation,
  onCollapse,
  onToggleExpand,
  expanded = false,
  showFullFile,
  onToggleFullFile
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
  wrapLines: boolean
  onToggleWrap?: () => void
  flush?: boolean
  navigation?: ReactElement
  onCollapse?: () => void
  onToggleExpand?: () => void
  expanded?: boolean
  showFullFile?: boolean
  onToggleFullFile?: () => void
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
          className="min-w-0 flex-1 text-[13px] font-medium"
        />
      ) : (
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-ds-ink" title={name ?? ''}>
          {name ?? 'patch'}
        </span>
      )}
      {added != null || removed != null ? (
        <>
          <span className="shrink-0 text-[13.5px] tabular-nums">
            {(added ?? 0) > 0 ? <span className="text-ds-diff-added">+{added}</span> : null}
            {(added ?? 0) > 0 && (removed ?? 0) > 0 ? <span className="px-1 text-ds-faint">·</span> : null}
            {(removed ?? 0) > 0 ? <span className="text-ds-diff-removed">-{removed}</span> : null}
          </span>
          <DiffStatBar added={added} removed={removed} className="ds-diff-header-statbar w-12" />
        </>
      ) : null}
      {onToggleWrap ? (
        <Tooltip label={t('diffWrapLines')}>
          <button
            type="button"
            onClick={onToggleWrap}
            aria-label={t('diffWrapLines')}
            aria-pressed={wrapLines}
            className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded transition hover:bg-ds-hover ${wrapLines ? 'bg-ds-hover text-ds-ink' : 'text-ds-faint'}`}
          >
            <WrapText className="h-3.5 w-3.5" strokeWidth={1.85} />
          </button>
        </Tooltip>
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
      {navigation}
      {onToggleFullFile ? (
        <Tooltip label={t(showFullFile ? 'diffShowChangesOnly' : 'diffShowFullFile')}>
          <button
            type="button"
            onClick={onToggleFullFile}
            className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-ds-ink transition hover:bg-ds-hover active:scale-[0.96] ${showFullFile ? '' : 'bg-ds-hover'}`}
            aria-label={t(showFullFile ? 'diffShowChangesOnly' : 'diffShowFullFile')}
            aria-pressed={!showFullFile}
          ><FileDiff size={17} strokeWidth={2.2} /></button>
        </Tooltip>
      ) : null}
      {onToggleExpand ? (
        <Tooltip label={t(expanded ? 'inspectorRestoreDiff' : 'inspectorExpandDiff')}>
          <button
            type="button"
            onClick={onToggleExpand}
            className="inline-flex h-7 w-7 items-center justify-center rounded text-ds-ink transition hover:bg-ds-hover active:scale-[0.96]"
            aria-label={t(expanded ? 'inspectorRestoreDiff' : 'inspectorExpandDiff')}
            aria-pressed={expanded}
          >
            {expanded ? <Minimize2 size={17} strokeWidth={2.2} /> : <ArrowUpToLine size={17} strokeWidth={2.2} />}
          </button>
        </Tooltip>
      ) : null}
      {onCollapse ? (
        <Tooltip label={t('inspectorCollapseDiff')}>
          <button
            type="button"
            onClick={onCollapse}
            className="inline-flex h-7 w-7 items-center justify-center rounded text-ds-ink transition hover:bg-ds-hover active:scale-[0.96]"
            aria-label={t('inspectorCollapseDiff')}
          >
            <ArrowDownToLine size={17} strokeWidth={2.2} />
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

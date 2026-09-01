import { useLayoutEffect, useMemo, useRef, useState, type ReactElement } from 'react'
import { Check, ChevronDown, Columns2, Copy, MessageSquarePlus, Rows3 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { countDiffStats, extractDiffFilePath } from '../lib/diff-stats'
import { FileChip } from './chat/FileChip'

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

const LANG_BADGES: Array<{ test: RegExp; label: string; tone: string }> = [
  { test: /\.tsx?$/i, label: 'TS', tone: 'bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300' },
  { test: /\.jsx?$/i, label: 'JS', tone: 'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300' },
  { test: /\.json$/i, label: 'JSON', tone: 'bg-zinc-100 text-zinc-700 dark:bg-zinc-500/15 dark:text-zinc-300' },
  { test: /\.(css|scss|less)$/i, label: 'CSS', tone: 'bg-pink-100 text-pink-700 dark:bg-pink-500/15 dark:text-pink-300' },
  { test: /\.md$/i, label: 'MD', tone: 'bg-slate-100 text-slate-700 dark:bg-slate-500/15 dark:text-slate-300' },
  { test: /\.py$/i, label: 'PY', tone: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' },
  { test: /\.html?$/i, label: 'HTML', tone: 'bg-orange-100 text-orange-700 dark:bg-orange-500/15 dark:text-orange-300' },
  { test: /\.ya?ml$/i, label: 'YML', tone: 'bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300' },
  { test: /\.sh$/i, label: 'SH', tone: 'bg-zinc-100 text-zinc-700 dark:bg-zinc-500/15 dark:text-zinc-300' }
]

function parseDiff(patch: string, override?: string): ParsedDiff {
  const stats = countDiffStats(patch)
  return {
    filePath: extractDiffFilePath(patch, override) ?? null,
    added: stats?.added ?? 0,
    removed: stats?.removed ?? 0
  }
}

function badgeFor(name: string | null): { label: string; tone: string } {
  if (!name) return { label: 'TXT', tone: 'bg-zinc-100 text-zinc-700 dark:bg-zinc-500/15 dark:text-zinc-300' }
  for (const b of LANG_BADGES) if (b.test.test(name)) return { label: b.label, tone: b.tone }
  return { label: 'TXT', tone: 'bg-zinc-100 text-zinc-700 dark:bg-zinc-500/15 dark:text-zinc-300' }
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
  showHeader = true,
  follow = false
}: Props): ReactElement {
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
  const badge = badgeFor(fileLabel)
  const fillParent = maxHeight >= 9000

  const bodyLines = useMemo(() => filterBodyLines(patch.split('\n')), [patch])
  const unifiedRows = useMemo(() => buildUnifiedRows(bodyLines), [bodyLines])
  const splitRows = useMemo(() => buildSplitRows(bodyLines), [bodyLines])
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
  const metaPad = 'px-2'

  const header = showHeader ? (
    <DiffHeader
      badge={badge}
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
                      <td colSpan={4} className={`break-all ${metaPad} py-0.5 font-mono text-[12px]`}>
                        {row.meta}
                      </td>
                    </tr>
                  )
                }
                return (
                  <tr key={row.key}>
                    <td
                      className={`select-none px-1 text-right align-top font-mono text-[11px] tabular-nums text-ds-faint ${sideCls(row.leftKind)}`}
                    >
                      {row.leftNo ?? ''}
                    </td>
                    <td
                      className={`max-w-0 break-all whitespace-pre-wrap ${cellPad} align-top font-mono text-[12.5px] leading-[1.45] ${sideCls(row.leftKind)}`}
                    >
                      {row.leftText ?? '\u00a0'}
                    </td>
                    <td
                      className={`select-none border-l border-ds-border-muted/50 px-1 text-right align-top font-mono text-[11px] tabular-nums text-ds-faint ${sideCls(row.rightKind)}`}
                    >
                      {row.rightNo ?? ''}
                    </td>
                    <td
                      className={`max-w-0 break-all whitespace-pre-wrap ${cellPad} align-top font-mono text-[12.5px] leading-[1.45] ${sideCls(row.rightKind)}`}
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
              {unifiedRows.map((row) => (
                <tr key={row.key} className={row.cls}>
                  <td className="select-none px-1 text-right align-top font-mono text-[11px] tabular-nums text-ds-faint">
                    {row.oldNo ?? ''}
                  </td>
                  <td className="select-none border-r border-ds-border-muted/40 px-1 text-right align-top font-mono text-[11px] tabular-nums text-ds-faint">
                    {row.newNo ?? ''}
                  </td>
                  <td className="max-w-0 break-all whitespace-pre-wrap px-2 align-top font-mono text-[12.5px] leading-[1.45]">
                    {row.text || '\u00a0'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

function DiffHeader({
  badge,
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
  onCollapse
}: {
  badge: { label: string; tone: string }
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
      <span
        className={`shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold ${badge.tone}`}
      >
        {badge.label}
      </span>
      {filePath ? (
        <FileChip
          path={filePath}
          label={name ?? undefined}
          variant="list"
          skipValidation
          className="min-w-0 flex-1 text-[12.5px] font-medium"
        />
      ) : (
        <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-ds-ink" title={name ?? ''}>
          {name ?? 'patch'}
        </span>
      )}
      {added != null || removed != null ? (
        <span className="shrink-0 text-[12px] tabular-nums">
          {(added ?? 0) > 0 ? <span className="text-ds-diff-added">+{added}</span> : null}
          {(added ?? 0) > 0 && (removed ?? 0) > 0 ? <span className="px-1 text-ds-faint">·</span> : null}
          {(removed ?? 0) > 0 ? <span className="text-ds-diff-removed">-{removed}</span> : null}
        </span>
      ) : null}
      {showStyleToggle ? (
        <div className="flex shrink-0 items-center rounded border border-ds-border-muted/70 p-0.5">
          <button
            type="button"
            onClick={() => onDiffStyleChange('unified')}
            className={`rounded px-1 py-0.5 transition ${
              diffStyle === 'unified' ? 'bg-ds-hover text-ds-ink' : 'text-ds-faint hover:text-ds-muted'
            }`}
            title="Unified"
            aria-label="Unified diff"
            aria-pressed={diffStyle === 'unified'}
          >
            <Rows3 className="h-3.5 w-3.5" strokeWidth={1.85} />
          </button>
          <button
            type="button"
            onClick={() => onDiffStyleChange('split')}
            className={`rounded px-1 py-0.5 transition ${
              diffStyle === 'split' ? 'bg-ds-hover text-ds-ink' : 'text-ds-faint hover:text-ds-muted'
            }`}
            title="Split"
            aria-label="Split diff"
            aria-pressed={diffStyle === 'split'}
          >
            <Columns2 className="h-3.5 w-3.5" strokeWidth={1.85} />
          </button>
        </div>
      ) : null}
      {onAddToChat ? (
        <button
          type="button"
          onClick={onAddToChat}
          className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
          aria-label={t('workspaceEditorAddToChat')}
          title={t('workspaceEditorAddToChat')}
        >
          <MessageSquarePlus className="h-3.5 w-3.5" strokeWidth={1.85} />
        </button>
      ) : null}
      {onCollapse ? (
        <button
          type="button"
          onClick={onCollapse}
          className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink active:scale-[0.96]"
          aria-label={t('inspectorCollapseDiff')}
          title={t('inspectorCollapseDiff')}
        >
          <ChevronDown className="h-3.5 w-3.5" strokeWidth={1.9} />
        </button>
      ) : (
        <button
          type="button"
          onClick={onCopy}
          className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
          aria-label="Copy diff"
          title="Copy diff"
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-ds-diff-added" strokeWidth={2} />
          ) : (
            <Copy className="h-3.5 w-3.5" strokeWidth={1.8} />
          )}
        </button>
      )}
    </div>
  )
}

import { useEffect, useMemo, useState, type ReactElement } from 'react'
import {
  ChevronRight,
  ExternalLink,
  FileEdit,
  GitFork,
  Loader2,
  Package,
  Plug,
  RefreshCw,
  Settings2,
  X
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { formatComposerModelLabel } from '../../lib/composer-model-label'
import { useChatStore } from '../../store/chat-store'

import type { ChatBlock, NormalizedThread } from '../../agent/types'
import type { ComposerActionCommandId } from '../../lib/composer-slash-commands'
import { countDiffStats, extractDiffFilePath, looksLikeUnifiedDiff } from '../../lib/diff-stats'
import { listMcpServers, setMcpServerEnabled } from '../../lib/mcp-json-merge'
import {
  contextBucketTokens,
  fallbackContextBreakdown,
  formatTokenCount,
  snapshotFromContextBreakdown,
  type ContextBreakdownJson
} from '../../lib/estimate-context-usage'

type Notice = { tone: 'info' | 'error' | 'success'; text: string }

type Props = {
  command: ComposerActionCommandId
  commandArgs: string
  blocks: ChatBlock[]
  model: string
  modelOptions: string[]
  runtimeReady: boolean
  busy: boolean
  activeThread: NormalizedThread | null
  onModelChange: (model: string) => void
  onCompact: () => Promise<void>
  onFork: () => Promise<void>
  onOpenDiff: () => void
  onClose: () => void
}

const buttonClass =
  'inline-flex items-center justify-center gap-1.5 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[12px] font-medium text-ds-ink transition hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-45'

function PanelHeader({
  title,
  subtitle,
  onClose
}: {
  title: string
  subtitle: string
  onClose: () => void
}): ReactElement {
  return (
    <div className="flex items-start gap-3 border-b border-ds-border-muted px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="text-[14px] font-semibold text-ds-ink">{title}</div>
        <div className="mt-0.5 text-[11px] leading-5 text-ds-faint">{subtitle}</div>
      </div>
      <button
        type="button"
        onClick={onClose}
        className="rounded-full p-1 text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
        aria-label="Close"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  )
}

function NoticeView({ notice }: { notice: Notice | null }): ReactElement | null {
  if (!notice) return null
  const tone =
    notice.tone === 'error'
      ? 'border-red-300/70 bg-red-50 text-red-800 dark:border-red-800/70 dark:bg-red-950/25 dark:text-red-200'
      : notice.tone === 'success'
        ? 'border-emerald-300/70 bg-emerald-50 text-emerald-800 dark:border-emerald-800/70 dark:bg-emerald-950/25 dark:text-emerald-200'
        : 'border-ds-border bg-ds-main/60 text-ds-muted'
  return <div className={`rounded-xl border px-3 py-2 text-[11px] ${tone}`}>{notice.text}</div>
}

export function ComposerCommandPanel(props: Props): ReactElement {
  const { t } = useTranslation('common')
  const { command, onClose } = props
  const titles: Record<ComposerActionCommandId, string> = {
    model: t('composerCommandModelTitle'),
    context: t('composerCommandContextTitle'),
    compact: t('composerCommandCompactTitle'),
    mcp: t('composerCommandMcpTitle'),
    skills: t('composerCommandSkillsTitle'),
    diff: t('composerCommandDiffTitle'),
    fork: t('composerCommandForkTitle'),
    hooks: t('composerCommandHooksTitle')
  }
  return (
    <div className="ds-composer-command-popover absolute bottom-full left-[calc(50%-64px)] z-40 max-h-[min(500px,58vh)] w-[calc(100%_-_24px)] max-w-[680px] -translate-x-1/2 overflow-hidden rounded-t-[22px] rounded-b-[14px] shadow-[0_22px_60px_rgba(15,23,42,0.18)]">
      <PanelHeader title={titles[command]} subtitle={`/${command}`} onClose={onClose} />
      <div className="max-h-[min(450px,52vh)] overflow-y-auto p-4">
        {command === 'model' ? <ModelPanel {...props} /> : null}
        {command === 'context' ? <ContextPanel {...props} /> : null}
        {command === 'compact' ? <CompactPanel {...props} /> : null}
        {command === 'mcp' ? <McpPanel runtimeReady={props.runtimeReady} /> : null}
        {command === 'skills' ? <SkillsPanel runtimeReady={props.runtimeReady} /> : null}
        {command === 'diff' ? <DiffPanel blocks={props.blocks} onOpenDiff={props.onOpenDiff} /> : null}
        {command === 'fork' ? <ForkPanel {...props} /> : null}
        {command === 'hooks' ? <HooksPanel /> : null}
      </div>
      <div className="ds-composer-command-ribbon" aria-hidden />
    </div>
  )
}

function ModelPanel({
  commandArgs,
  model,
  modelOptions,
  onModelChange,
  onClose
}: Props): ReactElement {
  const query = commandArgs.trim().toLowerCase()
  const options = modelOptions.filter((item) => !query || item.toLowerCase().includes(query))
  const composerModelMeta = useChatStore((s) => s.composerModelMeta)
  return (
    <div className="space-y-2">
      {options.map((item) => (
        <button
          key={item}
          type="button"
          onClick={() => {
            onModelChange(item)
            onClose()
          }}
          className={`flex w-full min-w-0 items-center justify-center rounded-xl px-3 py-2.5 text-center text-[13px] font-medium transition ${
            item === model ? 'bg-accent/10 text-ds-ink' : 'text-ds-muted hover:bg-ds-hover'
          }`}
        >
          <span className="truncate whitespace-nowrap">{formatComposerModelLabel(item, composerModelMeta)}</span>
        </button>
      ))}
      {options.length === 0 ? <div className="text-[12px] text-ds-faint">No matching models.</div> : null}
    </div>
  )
}

function ContextPanel({ blocks, model, runtimeReady, activeThread }: Props): ReactElement {
  const [breakdown, setBreakdown] = useState<ContextBreakdownJson | null>(null)
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    if (!runtimeReady || !activeThread) return
    let cancelled = false
    setLoading(true)
    void window.dsGui
      .runtimeRequest(`/v1/threads/${encodeURIComponent(activeThread.id)}/context`, 'GET')
      .then((result) => {
        if (result.ok && !cancelled) setBreakdown(JSON.parse(result.body) as ContextBreakdownJson)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [activeThread, runtimeReady])
  const effective = breakdown ?? fallbackContextBreakdown(blocks, model)
  const usage = snapshotFromContextBreakdown(effective)
  const rows = [
    ['System', contextBucketTokens(effective, 'system_prompt')],
    ['Tools', contextBucketTokens(effective, 'tool_definitions')],
    ['MCP', contextBucketTokens(effective, 'mcp')],
    ['Skills', contextBucketTokens(effective, 'skills')],
    ['Rules', contextBucketTokens(effective, 'rules')],
    ['Conversation', contextBucketTokens(effective, 'conversation')]
  ] as const
  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-3">
        <div className="text-[28px] font-semibold tabular-nums text-ds-ink">{Math.round(usage.percent)}%</div>
        <div className="text-right text-[12px] text-ds-muted">
          {loading ? 'Refreshing…' : `${formatTokenCount(usage.usedTokens)} / ${formatTokenCount(usage.maxTokens)}`}
        </div>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-ds-border">
        <div className="h-full rounded-full bg-accent" style={{ width: `${Math.min(100, usage.percent)}%` }} />
      </div>
      <div className="grid grid-cols-2 gap-2">
        {rows.map(([label, value]) => (
          <div key={label} className="rounded-xl bg-ds-main/60 px-3 py-2">
            <div className="text-[11px] text-ds-faint">{label}</div>
            <div className="mt-1 text-[13px] font-medium tabular-nums text-ds-ink">{formatTokenCount(value)}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

function CompactPanel({ activeThread, busy, runtimeReady, onCompact, onClose }: Props): ReactElement {
  const [working, setWorking] = useState(false)
  const disabled = !activeThread || busy || !runtimeReady || working
  return (
    <div className="space-y-4">
      <p className="text-[12px] leading-6 text-ds-muted">
        Summarize older conversation context while keeping the current thread active.
      </p>
      <button
        type="button"
        disabled={disabled}
        onClick={() => {
          setWorking(true)
          void onCompact().finally(() => {
            setWorking(false)
            onClose()
          })
        }}
        className={buttonClass}
      >
        {working ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
        Compact context
      </button>
      {!activeThread ? <div className="text-[11px] text-ds-faint">Start a thread first.</div> : null}
    </div>
  )
}

function McpPanel({ runtimeReady }: { runtimeReady: boolean }): ReactElement {
  const [raw, setRaw] = useState('')
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState<Notice | null>(null)
  const load = (): void => {
    setLoading(true)
    void window.dsGui.getMcpConfigFile().then((result) => setRaw(result.content)).finally(() => setLoading(false))
  }
  useEffect(load, [])
  const servers = useMemo(() => {
    try {
      return listMcpServers(raw)
    } catch {
      return []
    }
  }, [raw])
  const toggle = async (id: string, enabled: boolean): Promise<void> => {
    try {
      const next = setMcpServerEnabled(raw, id, enabled)
      await window.dsGui.setMcpConfigFile(next)
      setRaw(next)
      if (runtimeReady) await window.dsGui.runtimeRequest('/v1/mcp/startup', 'POST')
      setNotice({ tone: 'success', text: `${id} ${enabled ? 'enabled' : 'disabled'}.` })
    } catch (error) {
      setNotice({ tone: 'error', text: error instanceof Error ? error.message : String(error) })
    }
  }
  if (loading) return <Loader2 className="h-4 w-4 animate-spin text-ds-muted" />
  return (
    <div className="space-y-3">
      {servers.map((server) => (
        <button key={server.id} type="button" onClick={() => void toggle(server.id, !server.enabled)} className="flex w-full items-center justify-between rounded-xl bg-ds-main/60 px-3 py-3 text-left">
          <span className="min-w-0"><span className="flex items-center gap-2 text-[13px] font-medium text-ds-ink"><Plug className="h-4 w-4" />{server.id}</span><span className="mt-1 block truncate font-mono text-[10px] text-ds-faint">{server.summary}</span></span>
          <span className={server.enabled ? 'text-emerald-600' : 'text-ds-faint'}>{server.enabled ? 'On' : 'Off'}</span>
        </button>
      ))}
      {servers.length === 0 ? <div className="text-[12px] text-ds-faint">No MCP servers configured.</div> : null}
      <NoticeView notice={notice} />
    </div>
  )
}

function SkillsPanel({ runtimeReady }: { runtimeReady: boolean }): ReactElement {
  const [skills, setSkills] = useState<Array<{ name: string; description?: string }>>([])
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    if (!runtimeReady) {
      setLoading(false)
      return
    }
    void window.dsGui.runtimeRequest('/v1/skills', 'GET').then((result) => {
      if (result.ok) setSkills((JSON.parse(result.body) as { skills?: typeof skills }).skills ?? [])
    }).finally(() => setLoading(false))
  }, [runtimeReady])
  if (loading) return <Loader2 className="h-4 w-4 animate-spin text-ds-muted" />
  return (
    <div className="space-y-2">
      {skills.map((skill) => (
        <div key={skill.name} className="rounded-xl bg-ds-main/60 px-3 py-2.5">
          <div className="flex items-center gap-2 text-[13px] font-medium text-ds-ink"><Package className="h-4 w-4" />{skill.name}</div>
          {skill.description ? <div className="mt-1 text-[11px] text-ds-faint">{skill.description}</div> : null}
        </div>
      ))}
      {skills.length === 0 ? <div className="text-[12px] text-ds-faint">No skills discovered.</div> : null}
    </div>
  )
}

function DiffPanel({ blocks, onOpenDiff }: { blocks: ChatBlock[]; onOpenDiff: () => void }): ReactElement {
  const changes = blocks.flatMap((block) => {
    if (block.kind !== 'tool' || block.toolKind !== 'file_change' || !looksLikeUnifiedDiff(block.detail ?? '')) return []
    return [{ id: block.id, path: extractDiffFilePath(block.detail ?? '', block.filePath), stats: countDiffStats(block.detail) }]
  })
  return (
    <div className="space-y-3">
      {changes.map((change) => (
        <div key={change.id} className="flex items-center justify-between rounded-xl bg-ds-main/60 px-3 py-2.5">
          <span className="flex min-w-0 items-center gap-2 truncate text-[12px] text-ds-ink"><FileEdit className="h-4 w-4 shrink-0" />{change.path ?? 'Changed file'}</span>
          {change.stats ? <span className="shrink-0 font-mono text-[10px]"><span className="text-ds-diff-added">+{change.stats.added}</span> <span className="text-ds-diff-removed">-{change.stats.removed}</span></span> : null}
        </div>
      ))}
      <button type="button" disabled={changes.length === 0} onClick={onOpenDiff} className={buttonClass}>Open change inspector <ChevronRight className="h-4 w-4" /></button>
    </div>
  )
}

function ForkPanel({ activeThread, busy, runtimeReady, onFork, onClose }: Props): ReactElement {
  const [working, setWorking] = useState(false)
  return (
    <div className="space-y-4">
      <div className="rounded-xl bg-ds-main/60 px-3 py-3">
        <div className="flex items-center gap-2 text-[13px] font-medium text-ds-ink"><GitFork className="h-4 w-4" />{activeThread?.title ?? 'No active thread'}</div>
        {activeThread ? <div className="mt-1 text-[11px] text-ds-faint">{activeThread.model}</div> : null}
      </div>
      <button type="button" disabled={!activeThread || busy || !runtimeReady || working} onClick={() => {
        setWorking(true)
        void onFork().finally(() => {
          setWorking(false)
          onClose()
        })
      }} className={buttonClass}>
        {working ? <Loader2 className="h-4 w-4 animate-spin" /> : <GitFork className="h-4 w-4" />}Fork thread
      </button>
    </div>
  )
}

function HooksPanel(): ReactElement {
  const [paths, setPaths] = useState<{ configPath: string; hooksDir: string } | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  useEffect(() => {
    void window.dsGui.getDeepseekPaths().then(setPaths)
  }, [])
  return (
    <div className="space-y-3">
      <div className="rounded-xl bg-ds-main/60 px-3 py-3">
        <div className="flex items-center gap-2 text-[13px] font-medium text-ds-ink"><Settings2 className="h-4 w-4" />Hooks configuration</div>
        <div className="mt-2 break-all font-mono text-[10px] text-ds-faint">{paths?.configPath ?? 'Loading…'} · [hooks]</div>
        <div className="mt-1 break-all font-mono text-[10px] text-ds-faint">{paths?.hooksDir ?? ''}</div>
      </div>
      <button type="button" onClick={() => void window.dsGui.openHooksDir().then((result) => {
        if (!result.ok) setNotice({ tone: 'error', text: result.message ?? 'Could not open hooks folder.' })
      })} className={buttonClass}><ExternalLink className="h-4 w-4" />Open hooks folder</button>
      <NoticeView notice={notice} />
    </div>
  )
}

import { useEffect, useMemo, useRef, useState, type ReactElement } from 'react'
import { ArrowDown, ChevronRight } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { ChatBlock } from '../../agent/types'
import { useChatStore } from '../../store/chat-store'
import { useRunPanelStore, type RunTarget } from '../../store/run-panel-store'
import { extractTasksFromBlocks, isResumableTaskStatus, taskListTitle } from '../../lib/extract-tasks-from-blocks'
import { extractSubagentsFromBlocks, subagentListTitle } from '../../lib/extract-subagents-from-blocks'
import { buildSubagentTreeNodes, resolveSubagentFlowItems, type SubagentBlock } from '../../lib/run-subagent-flow'
import { groupRunActivity, isRunActive, runActionCount, runDisplayTitle, runStatusKey } from '../../lib/run-activity'
import { timelineToFlowItems } from '../../lib/task-step-flow'
import { useLiveTasks, resumeTask, resumeThreadAgent } from '../../hooks/use-thread-tasks'
import { useTaskRunDetail } from '../../hooks/use-task-run-detail'
import { formatTaskDuration } from '../chat/task-status'
import { StreamdownAssistant } from '../chat/StreamdownAssistant'
import { ToolCopyButton } from '../chat/tool/primitives'
import { RunActivity, RunStateIcon } from './RunActivity'
import { RunSwitcher, type RunOption } from './RunSwitcher'
import './run-panel.css'

export function RunPanel(): ReactElement {
  const { t } = useTranslation('common')
  const threadId = useChatStore((s) => s.activeThreadId)
  const blocks = useChatStore((s) => s.blocks)
  const target = useRunPanelStore((s) => s.target)
  const open = useRunPanelStore((s) => s.open)
  const baseTasks = useMemo(() => extractTasksFromBlocks(blocks), [blocks])
  const tasks = useLiveTasks(baseTasks)
  const agents = useMemo(() => extractSubagentsFromBlocks(blocks), [blocks])
  const current = target?.threadId === threadId ? target : null
  const options: RunOption[] = [
    ...tasks.map((task) => ({ kind: 'task' as const, id: task.id, label: runDisplayTitle(taskListTitle(task)), status: task.status })),
    ...agents.map((agent) => ({ kind: 'subagent' as const, id: agent.agentId, label: runDisplayTitle(subagentListTitle(agent, 90)), status: agent.status }))
  ]
  const select = (option: RunOption): void => {
    if (threadId) open({ threadId, kind: option.kind, id: option.id })
  }
  return (
    <div className="ds-run-panel" data-run-panel>
      {current ? (
        <RunDetail
          key={`${current.threadId}:${current.kind}:${current.id}`}
          target={current}
          blocks={blocks}
          options={options}
          onSelect={select}
        />
      ) : (
        <>
          <header className="ds-run-header"><RunSwitcher current={null} options={options} onSelect={select} /></header>
          <div className="ds-run-content"><p className="ds-run-empty">{t('runPanelSelect')}</p></div>
        </>
      )}
    </div>
  )
}

function RunDetail({ target, blocks, options, onSelect }: {
  target: RunTarget
  blocks: ChatBlock[]
  options: RunOption[]
  onSelect: (option: RunOption) => void
}): ReactElement {
  const { t } = useTranslation('common')
  const [refresh, setRefresh] = useState(0)
  const isTask = target.kind === 'task'
  const { detail, loading, failed } = useTaskRunDetail(isTask ? target.id : null, refresh)
  const related = useMemo(() => blocks.filter((block): block is SubagentBlock => block.kind === 'subagent'), [blocks])
  const root = related.find((block) => block.agentId === target.id)
  const [selectedId, setSelectedId] = useState(target.id)
  const selected = related.find((block) => block.agentId === selectedId)
  const worker = related.flatMap((block) => block.workers ?? []).find((item) => item.id === selectedId)
  const agent = selected ?? root
  const option = options.find((item) => item.kind === target.kind && item.id === target.id)
  const status = isTask ? detail?.status ?? option?.status : worker?.status ?? agent?.status
  const active = isRunActive(status)
  const assignment = isTask ? detail?.prompt : agent?.prompt
  const result = isTask ? detail?.resultSummary || detail?.error : selected?.summary
  const flow = useMemo(() => isTask
    ? timelineToFlowItems(detail?.timeline ?? [])
    : root ? resolveSubagentFlowItems(root, related, selectedId) : [],
  [isTask, detail?.timeline, root, related, selectedId])
  const tree = useMemo(() => root ? buildSubagentTreeNodes(root, related) : [], [root, related])
  const [resuming, setResuming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const resumableIds = agent?.cardKind === 'fanout' && selectedId === agent.agentId
    ? (agent.workers ?? []).filter((item) => item.status === 'failed' || item.status === 'cancelled').map((item) => item.id)
    : status === 'failed' || status === 'cancelled' ? [selectedId] : []
  const canResume = isTask ? !!detail && isResumableTaskStatus(detail.status) : resumableIds.length > 0
  const resume = async (): Promise<void> => {
    setResuming(true)
    setError(null)
    try {
      if (isTask) {
        await resumeTask(target.id)
        setRefresh((value) => value + 1)
      } else {
        for (const id of resumableIds) await resumeThreadAgent(target.threadId, id)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('taskResumeFailed'))
    } finally {
      setResuming(false)
    }
  }
  const scrollRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const following = useRef(active)
  const [showLatest, setShowLatest] = useState(false)
  useEffect(() => {
    const scroll = scrollRef.current
    const content = contentRef.current
    if (!scroll || !content) return
    const follow = (): void => {
      if (following.current) scroll.scrollTop = scroll.scrollHeight
    }
    follow()
    const observer = new ResizeObserver(follow)
    observer.observe(content)
    return () => observer.disconnect()
  }, [])
  const currentOption: RunOption = option ?? {
    kind: target.kind, id: target.id, label: assignment || target.id, status
  }
  const count = runActionCount(flow)
  const duration = formatTaskDuration(isTask ? detail?.durationMs ?? null
    : agent?.startedAt && agent?.finishedAt && !worker
      ? Math.max(0, Date.parse(agent.finishedAt) - Date.parse(agent.startedAt)) : null)
  const progressCount = groupRunActivity(flow).length
  const [processChoice, setProcessChoice] = useState<{ id: string; active: boolean; open: boolean } | null>(null)
  const processOpen = processChoice?.id === selectedId && processChoice.active === active ? processChoice.open : active
  return (
    <>
      <header className="ds-run-header">
        <RunSwitcher current={{ ...currentOption, status }} options={options.map((item) => item.kind === target.kind && item.id === target.id ? { ...item, status } : item)} onSelect={onSelect} />
        <span className="ds-run-status" data-status={status} role="status" title={duration || undefined}>
          <RunStateIcon status={status} />{t(runStatusKey(status))}
        </span>
        {canResume ? <button type="button" disabled={resuming} onClick={() => void resume()} className="ds-run-resume">{t(resuming ? 'taskResuming' : 'taskResume')}</button> : null}
      </header>
      <div className="ds-run-detail">
        <div ref={scrollRef} className="ds-run-scroll" onScroll={() => {
          const el = scrollRef.current!
          following.current = el.scrollHeight - el.scrollTop - el.clientHeight < 64
          setShowLatest(!following.current)
        }}>
          <div ref={contentRef} className="ds-run-content">
            {assignment ? (
              <details className="ds-run-context" onToggle={() => { following.current = false; setShowLatest(true) }}>
                <summary><ChevronRight className="ds-run-chevron" /><span className="ds-run-phase-heading"><span className="ds-run-phase-label">{t('runPanelAssignment')}</span><span className="ds-run-phase-preview">{runDisplayTitle(assignment)}</span></span></summary>
                <div className="ds-run-assignment ds-markdown ds-markdown--answer"><StreamdownAssistant text={assignment} streaming={false} /></div>
              </details>
            ) : null}
            {tree.length > 1 ? (
              <div className="ds-run-children" aria-label={t('subagentTreeTitle')}>
                {tree.map((node) => (
                  <button key={node.id} type="button" title={node.id} onClick={() => setSelectedId(node.id)} aria-pressed={node.id === selectedId}>
                    <RunStateIcon status={node.status} />{node.label} · {node.id.slice(-4)}
                  </button>
                ))}
              </div>
            ) : null}
            {error || failed ? <p role="alert" className="ds-run-error">{error || t('runPanelLoadFailed')}</p> : null}
            {isTask && loading ? <p className="ds-run-empty">{t('contextRailTaskLoading')}</p> : null}
            {!isTask && !root ? <p className="ds-run-empty">{t('runPanelUnavailable')}</p> : null}
            <section className="ds-run-process">
              <button type="button" className="ds-run-process-toggle" aria-expanded={processOpen} onClick={() => {
                following.current = false
                setShowLatest(true)
                setProcessChoice({ id: selectedId, active, open: !processOpen })
              }}>
                <ChevronRight className="ds-run-chevron" />
                <span>{t(active ? 'runPanelActions' : 'runPanelFinished')}</span>
                <span className="ds-run-process-stats">{[duration, t('runPanelProgressCount', { count: progressCount }), t('runPanelActionCount', { count })].filter(Boolean).join(' · ')}</span>
              </button>
              {processOpen ? <div onClickCapture={() => { following.current = false; setShowLatest(true) }}>
                <RunActivity key={selectedId} items={flow} active={active} followLatest={!showLatest} />
              </div> : null}
            </section>
            {result ? (
              <section className="ds-run-result">
                <div className="ds-run-result-header"><RunStateIcon status={status} /><span>{t(status === 'failed' ? 'subagentFailureReason' : 'runPanelResult')}</span><ToolCopyButton text={result} /></div>
                <div className="ds-markdown ds-markdown--answer"><StreamdownAssistant text={result} streaming={false} /></div>
              </section>
            ) : null}
          </div>
        </div>
        <footer className="ds-run-footer">
          <i className="ds-run-footer-dot" aria-hidden />
          <span>{t(active ? 'runPanelBackground' : 'runPanelFinished')}{count > 0 ? ` · ${t('runPanelActionCount', { count })}` : ''}</span>
          {showLatest ? (
            <button type="button" onClick={() => {
              following.current = true
              if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
              setShowLatest(false)
            }}><ArrowDown />{t('runPanelLatest')}</button>
          ) : null}
        </footer>
      </div>
    </>
  )
}

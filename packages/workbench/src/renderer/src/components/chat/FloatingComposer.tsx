import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement
} from 'react'
import {
  BarChart3,
  Bot,
  BrainCircuit,
  ChevronDown,
  Clock3,
  FileDiff,
  FileImage,
  FileText,
  GitFork,
  ListTodo,
  MessageCircleQuestion,
  Package,
  Plus,
  Plug,
  Send,
  Settings2,
  ShieldAlert,
  Shrink,
  Square,
  Gauge,
  Target,
  Workflow,
  X
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useChatStore } from '../../store/chat-store'
import { countPendingApprovals } from '../../store/chat-store-runtime-helpers'
import {
  filterComposerModelOptions,
  formatComposerModelLabel
} from '../../lib/composer-model-label'
import { normalizeWorkspaceRoot } from '../../lib/workspace-path'
import { getPetSlashQuery, type PetSlashMenuItem } from '../../lib/pet/pet-slash-commands'
import {
  isUnknownComposerSlashCommand,
  parseComposerActionCommand,
  type ComposerActionCommandId
} from '../../lib/composer-slash-commands'
import { ContextUsageMeter } from './ContextUsageMeter'
import { ComposerCommandPanel } from './ComposerCommandPanel'
import { GitBranchPicker } from './GitBranchPicker'
import {
  formatCompactNumber,
  formatCost,
  formatPercent,
  useThreadUsageState
} from '../../hooks/use-thread-usage'

export type ComposerMode = 'plan' | 'agent' | 'ask' | 'goal' | 'workflow'

type ComposerAttachment = {
  id: string
  path: string
}

type QueuedComposerMessage = {
  id: string
  text: string
}

type Props = {
  input: string
  setInput: (v: string) => void
  mode: ComposerMode
  setMode: (m: ComposerMode) => void
  busy: boolean
  runtimeReady: boolean
  hasActiveThread: boolean
  composerModel: string
  composerPickList: string[]
  onComposerModelChange: (modelId: string) => void
  queuedMessages: QueuedComposerMessage[]
  onRemoveQueuedMessage: (id: string) => void
  onSend: (text: string) => void
  onInterrupt: () => void
  onCompact: () => Promise<void>
  onFork: () => Promise<void>
  onOpenDiff: () => void
  stageCentered?: boolean
  useChatStageWidth?: boolean
  petSlashCommands?: Array<{
    command: string
    token: string
    title: string
    description: string
    icon: ReactElement
  }>
  onApplyPetSlashCommand?: (command: string) => boolean
  filterPetSlashCommands?: (query: string) => PetSlashMenuItem[]
}

type SlashCommandId = ComposerMode | ComposerActionCommandId

type SlashCommand = {
  id: SlashCommandId
  kind: 'mode' | 'action'
  title: string
  description: string
  keywords: string[]
  icon: ReactElement
}

type PetSlashCommandView = NonNullable<Props['petSlashCommands']>[number]

function getSlashQuery(input: string): string | null {
  const trimmed = input.trimStart()
  if (!trimmed.startsWith('/')) return null
  if (/\s/.test(trimmed)) return null
  return trimmed.slice(1).toLowerCase()
}

function buildOutboundMessage(attachments: ComposerAttachment[], input: string): string {
  const mentionLines = attachments.map((item) => `@${item.path}`)
  return [...mentionLines, input.trim()].filter(Boolean).join('\n')
}

export function FloatingComposer({
  input,
  setInput,
  mode,
  setMode,
  busy,
  runtimeReady,
  hasActiveThread,
  composerModel,
  composerPickList,
  onComposerModelChange,
  queuedMessages,
  onRemoveQueuedMessage,
  onSend,
  onInterrupt,
  onCompact,
  onFork,
  onOpenDiff,
  stageCentered = false,
  useChatStageWidth = true,
  petSlashCommands = [],
  onApplyPetSlashCommand,
  filterPetSlashCommands
}: Props): ReactElement {
  const { t, i18n } = useTranslation('common')
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const usageRefreshKey = useChatStore((s) => s.usageRefreshKey)
  const threads = useChatStore((s) => s.threads)
  const blocks = useChatStore((s) => s.blocks)
  const scrollToBlock = useChatStore((s) => s.scrollToBlock)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const shellRef = useRef<HTMLDivElement | null>(null)
  const composingRef = useRef(false)
  const [focused, setFocused] = useState(false)
  const [plusMenuOpen, setPlusMenuOpen] = useState(false)
  const [modelMenuOpen, setModelMenuOpen] = useState(false)
  const [attachNotice, setAttachNotice] = useState<string | null>(null)
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([])
  const [activeCommand, setActiveCommand] = useState<{
    id: ComposerActionCommandId
    args: string
  } | null>(null)
  const activeThreadWorkspace = activeThreadId
    ? threads.find((thread) => thread.id === activeThreadId)?.workspace
    : ''
  const activeThread = activeThreadId
    ? threads.find((thread) => thread.id === activeThreadId) ?? null
    : null
  const showThreadUsageFooter = hasActiveThread && runtimeReady
  const threadUsageState = useThreadUsageState(
    activeThreadId,
    showThreadUsageFooter,
    `${activeThread?.updatedAt ?? ''}:${busy ? 'busy' : 'idle'}:${usageRefreshKey}`,
    busy
  )
  const threadUsage = threadUsageState.usage
  const effectiveWorkspaceRoot = normalizeWorkspaceRoot(activeThreadWorkspace || workspaceRoot)

  const pendingApprovalCount = countPendingApprovals(blocks)
  const firstPendingApprovalId = blocks.find(
    (block) => block.kind === 'approval' && block.status === 'pending'
  )?.id

  const canCompose = runtimeReady && (hasActiveThread || !!effectiveWorkspaceRoot)
  const canChangeModel = canCompose && !busy
  const outboundPreview = buildOutboundMessage(attachments, input)
  const canSend = canCompose && outboundPreview.length > 0
  const petSlashQuery = getPetSlashQuery(input)
  const slashQuery = petSlashQuery == null ? getSlashQuery(input) : null
  const [selectedCommandIndex, setSelectedCommandIndex] = useState(0)

  const modelOptions = useMemo(
    () => filterComposerModelOptions(composerModel, composerPickList),
    [composerModel, composerPickList]
  )
  const activeModelId = composerModel.trim() || modelOptions[0] || 'deepseek-v4-pro'
  const activeModelLabel = formatComposerModelLabel(activeModelId)

  const modeLabel =
    mode === 'plan'
      ? t('composerModePlan')
      : mode === 'ask'
        ? t('composerModeAsk')
        : mode === 'goal'
          ? t('composerModeGoal')
          : mode === 'workflow'
            ? t('composerModeWorkflow')
            : t('composerModeAgent')
  const ModeIcon =
    mode === 'plan'
      ? ListTodo
      : mode === 'ask'
        ? MessageCircleQuestion
        : mode === 'goal'
          ? Target
          : mode === 'workflow'
            ? Workflow
            : Bot

  const placeholder = !runtimeReady
    ? t('runtimeActionNeedsConnection')
    : !hasActiveThread && !effectiveWorkspaceRoot
      ? t('workspaceRequiredToCreateThread')
      : busy
        ? t('composerQueuePlaceholder')
        : t('composerDefaultPlaceholder')
  const primaryActionDisabled = !canSend

  const slashCommands = useMemo<SlashCommand[]>(() => {
    const commands: SlashCommand[] = [
      {
        id: 'agent',
        kind: 'mode',
        title: t('slashCommandAgentTitle'),
        description:
          mode === 'agent'
            ? t('slashCommandAgentActiveDescription')
            : t('slashCommandAgentDescription'),
        keywords: ['agent', 'default', 'normal', '代理', '默认'],
        icon: <Bot className="h-4 w-4" strokeWidth={1.9} />
      },
      {
        id: 'plan',
        kind: 'mode',
        title: t('slashCommandPlanTitle'),
        description:
          mode === 'plan'
            ? t('slashCommandPlanActiveDescription')
            : t('slashCommandPlanDescription'),
        keywords: ['plan', 'planner', 'planning', '规划', '计划'],
        icon: <ListTodo className="h-4 w-4" strokeWidth={1.9} />
      },
      {
        id: 'ask',
        kind: 'mode',
        title: t('slashCommandAskTitle'),
        description:
          mode === 'ask'
            ? t('slashCommandAskActiveDescription')
            : t('slashCommandAskDescription'),
        keywords: ['ask', 'question', 'qa', '问答'],
        icon: <MessageCircleQuestion className="h-4 w-4" strokeWidth={1.9} />
      },
      {
        id: 'goal',
        kind: 'mode',
        title: t('slashCommandGoalTitle'),
        description:
          mode === 'goal'
            ? t('slashCommandGoalActiveDescription')
            : t('slashCommandGoalDescription'),
        keywords: ['goal', 'objective', 'target', '目标'],
        icon: <Target className="h-4 w-4" strokeWidth={1.9} />
      },
      {
        id: 'workflow',
        kind: 'mode',
        title: t('slashCommandWorkflowTitle'),
        description:
          mode === 'workflow'
            ? t('slashCommandWorkflowActiveDescription')
            : t('slashCommandWorkflowDescription'),
        keywords: ['workflow', 'flow', 'pipeline', '工作流'],
        icon: <Workflow className="h-4 w-4" strokeWidth={1.9} />
      },
      {
        id: 'model',
        kind: 'action',
        title: t('composerCommandModelTitle'),
        description: t('composerCommandModelDescription'),
        keywords: ['model', '模型'],
        icon: <Bot className="h-4 w-4" strokeWidth={1.9} />
      },
      {
        id: 'context',
        kind: 'action',
        title: t('composerCommandContextTitle'),
        description: t('composerCommandContextDescription'),
        keywords: ['context', 'tokens', '上下文'],
        icon: <Gauge className="h-4 w-4" strokeWidth={1.9} />
      },
      {
        id: 'compact',
        kind: 'action',
        title: t('composerCommandCompactTitle'),
        description: t('composerCommandCompactDescription'),
        keywords: ['compact', 'compress', '压缩'],
        icon: <Shrink className="h-4 w-4" strokeWidth={1.9} />
      },
      {
        id: 'memory',
        kind: 'action',
        title: t('composerCommandMemoryTitle'),
        description: t('composerCommandMemoryDescription'),
        keywords: ['memory', '记忆'],
        icon: <BrainCircuit className="h-4 w-4" strokeWidth={1.9} />
      },
      {
        id: 'mcp',
        kind: 'action',
        title: t('composerCommandMcpTitle'),
        description: t('composerCommandMcpDescription'),
        keywords: ['mcp', 'server', '服务器'],
        icon: <Plug className="h-4 w-4" strokeWidth={1.9} />
      },
      {
        id: 'skills',
        kind: 'action',
        title: t('composerCommandSkillsTitle'),
        description: t('composerCommandSkillsDescription'),
        keywords: ['skills', 'plugins', '技能', '插件'],
        icon: <Package className="h-4 w-4" strokeWidth={1.9} />
      },
      {
        id: 'diff',
        kind: 'action',
        title: t('composerCommandDiffTitle'),
        description: t('composerCommandDiffDescription'),
        keywords: ['diff', 'changes', '变更'],
        icon: <FileDiff className="h-4 w-4" strokeWidth={1.9} />
      },
      {
        id: 'fork',
        kind: 'action',
        title: t('composerCommandForkTitle'),
        description: t('composerCommandForkDescription'),
        keywords: ['fork', 'branch', '分支'],
        icon: <GitFork className="h-4 w-4" strokeWidth={1.9} />
      },
      {
        id: 'hooks',
        kind: 'action',
        title: t('composerCommandHooksTitle'),
        description: t('composerCommandHooksDescription'),
        keywords: ['hooks', '钩子'],
        icon: <Settings2 className="h-4 w-4" strokeWidth={1.9} />
      }
    ]
    return commands
  }, [mode, t])

  const filteredSlashCommands = useMemo(() => {
    if (slashQuery == null) return []
    if (!slashQuery) return slashCommands
    return slashCommands.filter((command) => {
      const haystack = [command.id, command.title, command.description, ...command.keywords]
      return haystack.some((part) => part.toLowerCase().includes(slashQuery))
    })
  }, [slashCommands, slashQuery])

  const filteredPetSlashCommands = useMemo(() => {
    if (petSlashQuery == null || petSlashCommands.length === 0) return []
    const filtered = filterPetSlashCommands
      ? filterPetSlashCommands(petSlashQuery).map((item) =>
          petSlashCommands.find((command) => command.token === item.token)
        )
      : petSlashCommands
    return filtered.filter((command): command is PetSlashCommandView => command != null)
  }, [filterPetSlashCommands, petSlashCommands, petSlashQuery])

  const highlightedSlashCommand =
    filteredSlashCommands.length > 0
      ? filteredSlashCommands[Math.min(selectedCommandIndex, filteredSlashCommands.length - 1)]
      : null
  const highlightedPetSlashCommand =
    filteredPetSlashCommands.length > 0
      ? filteredPetSlashCommands[
          Math.min(selectedCommandIndex, filteredPetSlashCommands.length - 1)
        ]
      : null
  const activeSlashMenu = petSlashQuery != null ? filteredPetSlashCommands : filteredSlashCommands
  const activeHighlightedSlashCommand =
    petSlashQuery != null ? highlightedPetSlashCommand : highlightedSlashCommand
  const primaryActionLabel = activeHighlightedSlashCommand
    ? t('slashCommandApply')
    : busy
      ? t('queueMessage')
      : t('send')

  const resizeTextarea = useCallback(() => {
    const el = textareaRef.current
    if (!el) return

    el.style.height = '0px'
    const nextHeight = Math.min(el.scrollHeight, 176)
    const minHeight = 44
    el.style.height = `${Math.max(nextHeight, minHeight)}px`
    el.style.overflowY = el.scrollHeight > 176 ? 'auto' : 'hidden'
  }, [])

  useLayoutEffect(() => {
    resizeTextarea()
  }, [attachments.length, canCompose, input, resizeTextarea])

  useEffect(() => {
    setActiveCommand(null)
  }, [activeThreadId])

  useEffect(() => {
    const el = textareaRef.current
    if (!el || typeof ResizeObserver === 'undefined') return

    let frame = 0
    let previousWidth = el.getBoundingClientRect().width
    const observer = new ResizeObserver(([entry]) => {
      const nextWidth = entry?.contentRect.width ?? el.getBoundingClientRect().width
      if (Math.abs(nextWidth - previousWidth) < 0.5) return
      previousWidth = nextWidth
      window.cancelAnimationFrame(frame)
      frame = window.requestAnimationFrame(resizeTextarea)
    })

    observer.observe(el)

    return () => {
      window.cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [resizeTextarea])

  useEffect(() => {
    setSelectedCommandIndex(0)
  }, [petSlashQuery, slashQuery])

  useEffect(() => {
    if (!plusMenuOpen && !modelMenuOpen) return
    const onPointerDown = (event: MouseEvent): void => {
      const target = event.target
      if (!(target instanceof Node) || !shellRef.current?.contains(target)) {
        setPlusMenuOpen(false)
        setModelMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [modelMenuOpen, plusMenuOpen])

  const focusComposer = (): void => {
    window.requestAnimationFrame(() => textareaRef.current?.focus())
  }

  const applySlashCommand = (command: SlashCommand): void => {
    if (command.kind === 'action') {
      setPlusMenuOpen(false)
      setModelMenuOpen(false)
      setActiveCommand({ id: command.id as ComposerActionCommandId, args: '' })
    } else {
      setMode(command.id as ComposerMode)
    }
    setInput('')
    focusComposer()
  }

  const applyPetSlashCommand = (command: string): void => {
    if (onApplyPetSlashCommand?.(command)) {
      setInput('')
      focusComposer()
    }
  }

  const clearAttachNotice = (): void => {
    setAttachNotice(null)
  }

  const pickAttachments = async (imagesOnly: boolean): Promise<void> => {
    clearAttachNotice()
    if (!effectiveWorkspaceRoot) {
      setAttachNotice(t('composerAttachNeedsWorkspace'))
      return
    }
    if (typeof window.dsGui === 'undefined') {
      setAttachNotice(t('preloadBridgeMissing'))
      return
    }
    if (typeof window.dsGui.pickWorkspaceFiles !== 'function') {
      setAttachNotice(t('composerAttachNeedRestart'))
      return
    }
    const result = await window.dsGui.pickWorkspaceFiles({
      workspaceRoot: effectiveWorkspaceRoot,
      imagesOnly
    })
    if (!result.ok) {
      setAttachNotice(result.message ?? t('composerAttachFailed'))
      return
    }
    if (result.paths.length === 0) return
    setAttachments((prev) => {
      const seen = new Set(prev.map((item) => item.path))
      const next = [...prev]
      for (const path of result.paths) {
        if (seen.has(path)) continue
        seen.add(path)
        next.push({ id: `att-${path}`, path })
      }
      return next
    })
    setPlusMenuOpen(false)
    focusComposer()
  }

  const removeAttachment = (id: string): void => {
    setAttachments((prev) => prev.filter((item) => item.id !== id))
  }

  const handlePrimaryAction = (): void => {
    if (petSlashQuery != null) {
      const trimmed = input.trim()
      if (/^\/pet\s*$/i.test(trimmed)) {
        if (onApplyPetSlashCommand?.(trimmed)) {
          setInput('')
          focusComposer()
        }
        return
      }
      if (highlightedPetSlashCommand) {
        applyPetSlashCommand(highlightedPetSlashCommand.command)
        return
      }
      if (trimmed && onApplyPetSlashCommand?.(trimmed)) {
        setInput('')
        focusComposer()
      }
      return
    }
    if (highlightedSlashCommand) {
      applySlashCommand(highlightedSlashCommand)
      return
    }
    const parsedCommand = parseComposerActionCommand(input)
    if (parsedCommand) {
      setActiveCommand(parsedCommand)
      setInput('')
      focusComposer()
      return
    }
    if (isUnknownComposerSlashCommand(input)) {
      setAttachNotice(t('composerCommandUnknown'))
      return
    }
    const payload = buildOutboundMessage(attachments, input)
    if (!payload.trim()) return
    setAttachments([])
    setInput('')
    onSend(payload)
  }

  return (
    <div
      className={`pointer-events-auto w-full ${
        useChatStageWidth ? 'ds-chat-stage px-3 pb-2 pt-0 sm:px-4' : 'max-w-none px-0 pb-2 pt-0'
      } ${stageCentered ? 'shrink-0 pb-1 pt-0' : 'pb-4 pt-1'}`}
    >
      {pendingApprovalCount > 0 ? (
        <div className="mb-2 rounded-[22px] border border-accent/30 bg-[linear-gradient(180deg,rgba(79,124,255,0.08),rgba(79,124,255,0.14))] px-4 py-3 shadow-sm backdrop-blur-xl">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="inline-flex min-w-0 items-center gap-2 text-[13px] font-medium text-ds-ink">
              <ShieldAlert className="h-4 w-4 shrink-0 text-accent" strokeWidth={1.9} />
              <span>
                {pendingApprovalCount === 1
                  ? t('approvalBannerSingle')
                  : t('approvalBannerMultiple', { count: pendingApprovalCount })}
              </span>
            </div>
            {firstPendingApprovalId ? (
              <button
                type="button"
                onClick={() => scrollToBlock(firstPendingApprovalId)}
                className="rounded-full border border-accent/25 bg-ds-elevated/80 px-3 py-1 text-[12px] font-semibold text-accent transition hover:bg-ds-card dark:bg-ds-elevated/80"
              >
                {t('approvalBannerJump')}
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
      {queuedMessages.length > 0 ? (
        <div className="mb-2 rounded-[22px] border border-ds-border bg-ds-card/88 px-4 py-3 shadow-sm backdrop-blur-xl">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="inline-flex items-center gap-2 text-[13px] font-medium text-ds-ink">
              <Clock3 className="h-3.5 w-3.5 text-ds-muted" strokeWidth={1.9} />
              <span>{t('queuedMessagesTitle', { count: queuedMessages.length })}</span>
            </div>
            <div className="text-[12px] text-ds-muted">{t('queuedMessagesHint')}</div>
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {queuedMessages.map((message, index) => (
              <div
                key={message.id}
                className="flex min-w-0 max-w-full items-center gap-2 rounded-full border border-ds-border-muted bg-ds-main/80 px-3 py-1.5 text-[13px] text-ds-ink"
              >
                <span className="shrink-0 text-ds-faint">{index + 1}.</span>
                <span className="max-w-[360px] truncate">{message.text}</span>
                <button
                  type="button"
                  onClick={() => onRemoveQueuedMessage(message.id)}
                  className="shrink-0 rounded-full p-0.5 text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
                  aria-label={t('queuedMessageRemove')}
                  title={t('queuedMessageRemove')}
                >
                  <X className="h-3.5 w-3.5" strokeWidth={2} />
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="relative">
        {activeCommand ? (
          <ComposerCommandPanel
            command={activeCommand.id}
            commandArgs={activeCommand.args}
            blocks={blocks}
            model={activeModelId}
            modelOptions={modelOptions}
            runtimeReady={runtimeReady}
            busy={busy}
            activeThread={activeThreadId ? threads.find((thread) => thread.id === activeThreadId) ?? null : null}
            onModelChange={onComposerModelChange}
            onCompact={onCompact}
            onFork={onFork}
            onOpenDiff={() => {
              onOpenDiff()
              setActiveCommand(null)
            }}
            onClose={() => setActiveCommand(null)}
          />
        ) : (slashQuery != null || petSlashQuery != null) ? (
          <div className="ds-composer-command-popover absolute bottom-full left-[calc(50%-64px)] z-30 flex max-h-[min(420px,50vh)] w-[calc(100%_-_24px)] max-w-[620px] -translate-x-1/2 flex-col overflow-hidden rounded-t-[22px] rounded-b-[14px] p-1.5 shadow-[0_20px_55px_rgba(15,23,42,0.16)]">
            <div className="shrink-0 px-3 pb-1.5 pt-1.5 text-[11px] font-medium uppercase tracking-[0.12em] text-ds-faint">
              {petSlashQuery != null ? t('petSlashCommandMenuTitle') : t('slashCommandMenuTitle')}
            </div>
            {petSlashQuery != null ? (
              filteredPetSlashCommands.length > 0 ? (
                <div className="min-h-0 flex-1 overflow-y-auto">
                  {filteredPetSlashCommands.map((command) => {
                    const active = highlightedPetSlashCommand?.command === command.command
                    return (
                      <button
                        key={command.command}
                        type="button"
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => applyPetSlashCommand(command.command)}
                        className={`flex w-full items-center gap-2.5 rounded-[15px] px-2.5 py-2 text-left transition ${
                          active
                            ? 'bg-accent/10 text-ds-ink shadow-[inset_0_0_0_1px_rgba(0,136,255,0.14)]'
                            : 'text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
                        }`}
                      >
                        <span
                          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ${
                            active ? 'bg-accent/12 text-accent' : 'bg-ds-hover text-ds-muted'
                          }`}
                        >
                          {command.icon}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block text-[13px] font-semibold text-inherit">
                            {command.title}
                          </span>
                          <span className="mt-0.5 block truncate text-[11px] leading-4 text-ds-faint">
                            {command.description}
                          </span>
                        </span>
                        <span className="rounded-full border border-ds-border-muted px-2 py-0.5 text-[10px] font-semibold text-ds-faint">
                          {command.command}
                        </span>
                      </button>
                    )
                  })}
                </div>
              ) : (
                <div className="rounded-[20px] border border-dashed border-ds-border-muted px-4 py-5 text-[13px] text-ds-faint">
                  {t('slashCommandEmpty')}
                </div>
              )
            ) : filteredSlashCommands.length > 0 ? (
              <div className="min-h-0 flex-1 overflow-y-auto">
                {filteredSlashCommands.map((command) => {
                  const active = highlightedSlashCommand?.id === command.id
                  return (
                    <button
                      key={command.id}
                      type="button"
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => applySlashCommand(command)}
                      className={`flex w-full items-center gap-2.5 rounded-[15px] px-2.5 py-2 text-left transition ${
                        active
                          ? 'bg-accent/10 text-ds-ink shadow-[inset_0_0_0_1px_rgba(0,136,255,0.14)]'
                          : 'text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
                      }`}
                    >
                      <span
                        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ${
                          active ? 'bg-accent/12 text-accent' : 'bg-ds-hover text-ds-muted'
                        }`}
                      >
                        {command.icon}
                      </span>
                      <span className="min-w-0 flex-1">
                          <span className="block text-[13px] font-semibold text-inherit">
                          {command.title}
                        </span>
                          <span className="mt-0.5 block truncate text-[11px] leading-4 text-ds-faint">
                          {command.description}
                        </span>
                      </span>
                      <span className="flex shrink-0 flex-col items-end gap-1">
                        <span className="rounded-full border border-ds-border-muted px-2 py-0.5 text-[10px] font-semibold text-ds-faint">
                          /{command.id}
                        </span>
                        {command.kind === 'mode' && command.id === mode ? (
                          <span className="rounded-full bg-accent/10 px-2 py-0.5 text-[10px] font-semibold text-accent">
                            {t('slashCommandCurrent')}
                          </span>
                        ) : null}
                      </span>
                    </button>
                  )
                })}
              </div>
            ) : (
              <div className="rounded-[20px] border border-dashed border-ds-border-muted px-4 py-5 text-[13px] text-ds-faint">
                {t('slashCommandEmpty')}
              </div>
            )}
            <div className="ds-composer-command-ribbon" aria-hidden />
          </div>
        ) : null}

        <div
          ref={shellRef}
            className={`ds-composer-shell ds-chat-composer ds-frosted flex w-full flex-col gap-2.5 px-4 py-3 transition sm:px-5 ${
              stageCentered ? 'ds-composer-empty' : ''
            } ${focused ? 'ds-chat-composer-focus' : ''}`}
        >
          {attachments.length > 0 ? (
            <div className="flex flex-wrap gap-2 px-1 pt-1">
              {attachments.map((item) => (
                <div
                  key={item.id}
                  className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-ds-border-muted bg-ds-main/80 px-2.5 py-1 text-[12px] text-ds-ink"
                >
                  <span className="truncate font-mono">@{item.path}</span>
                  <button
                    type="button"
                    onClick={() => removeAttachment(item.id)}
                    className="shrink-0 rounded-full p-0.5 text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
                    aria-label={t('composerAttachmentRemove')}
                  >
                    <X className="h-3 w-3" strokeWidth={2} />
                  </button>
                </div>
              ))}
            </div>
          ) : null}

          <textarea
            ref={textareaRef}
            rows={stageCentered ? 2 : 1}
            className={`ds-no-drag block min-w-0 w-full resize-none break-words bg-transparent px-2 py-2.5 text-[15px] leading-[1.55] text-ds-ink placeholder:text-ds-faint focus:outline-none [overflow-wrap:anywhere] ${
              stageCentered ? 'min-h-[76px]' : 'min-h-[52px]'
            } ${canCompose ? '' : 'opacity-80'}`}
            placeholder={placeholder}
            value={input}
            disabled={!canCompose}
            onChange={(e) => setInput(e.target.value)}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            onCompositionStart={() => {
              composingRef.current = true
            }}
            onCompositionEnd={() => {
              composingRef.current = false
            }}
            onKeyDown={(e) => {
              const sendByEnter =
                e.key === 'Enter' && !e.shiftKey && !e.metaKey && !e.ctrlKey
              const composing =
                e.nativeEvent.isComposing || composingRef.current || e.keyCode === 229

              if (!composing && (slashQuery != null || petSlashQuery != null)) {
                if (e.key === 'ArrowDown' && activeSlashMenu.length > 0) {
                  e.preventDefault()
                  setSelectedCommandIndex((current) => (current + 1) % activeSlashMenu.length)
                  return
                }
                if (e.key === 'ArrowUp' && activeSlashMenu.length > 0) {
                  e.preventDefault()
                  setSelectedCommandIndex((current) =>
                    current === 0 ? activeSlashMenu.length - 1 : current - 1
                  )
                  return
                }
                if (e.key === 'Escape') {
                  e.preventDefault()
                  setInput('')
                  return
                }
              }
              if (!composing && e.key === 'Escape' && activeCommand) {
                e.preventDefault()
                setActiveCommand(null)
                return
              }

              if (!sendByEnter || composing) return

              e.preventDefault()
              handlePrimaryAction()
            }}
          />

          <div className="flex items-center gap-2 px-1 pb-0.5">
            <div className="relative">
              <button
                type="button"
                disabled={!canCompose}
                onClick={() => {
                  setActiveCommand(null)
                  setModelMenuOpen(false)
                  clearAttachNotice()
                  setPlusMenuOpen((open) => !open)
                }}
                className="ds-no-drag inline-flex h-9 w-9 items-center justify-center rounded-full border border-ds-border bg-ds-card text-ds-muted shadow-sm transition hover:bg-ds-hover hover:text-ds-ink disabled:cursor-not-allowed disabled:opacity-50"
                aria-label={t('composerPlusMenu')}
                title={t('composerPlusMenu')}
              >
                <Plus className="h-4 w-4" strokeWidth={2} />
              </button>
              {plusMenuOpen ? (
                <div className="ds-glass absolute bottom-full left-0 z-40 mb-2 min-w-[220px] overflow-hidden rounded-2xl p-1.5">
                  <div className="px-2 py-1 text-[11px] font-medium uppercase tracking-wide text-ds-faint">
                    {t('composerModeSection')}
                  </div>
                  {(
                    [
                      { id: 'agent' as const, label: t('composerModeAgent'), icon: Bot },
                      { id: 'plan' as const, label: t('composerModePlan'), icon: ListTodo },
                      { id: 'ask' as const, label: t('composerModeAsk'), icon: MessageCircleQuestion },
                      { id: 'goal' as const, label: t('composerModeGoal'), icon: Target },
                      { id: 'workflow' as const, label: t('composerModeWorkflow'), icon: Workflow }
                    ] as const
                  ).map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => {
                        clearAttachNotice()
                        setMode(item.id)
                        setPlusMenuOpen(false)
                        focusComposer()
                      }}
                      className={`flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-[13px] transition ${
                        mode === item.id
                          ? 'bg-accent/10 font-semibold text-ds-ink'
                          : 'text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
                      }`}
                    >
                      <item.icon className="h-4 w-4 shrink-0" strokeWidth={1.8} />
                      <span>{item.label}</span>
                    </button>
                  ))}
                  <div className="my-1 border-t border-ds-border-muted" />
                  <div className="px-2 py-1 text-[11px] font-medium uppercase tracking-wide text-ds-faint">
                    {t('composerPlusAttachSection')}
                  </div>
                  <button
                    type="button"
                    disabled={!canCompose}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => void pickAttachments(false)}
                    className="flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-[13px] text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50"
                  >
                    <FileText className="h-4 w-4 shrink-0" strokeWidth={1.8} />
                    <span>{t('composerAttachFiles')}</span>
                  </button>
                  <button
                    type="button"
                    disabled={!canCompose}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => void pickAttachments(true)}
                    className="flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-[13px] text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50"
                  >
                    <FileImage className="h-4 w-4 shrink-0" strokeWidth={1.8} />
                    <span>{t('composerAttachImages')}</span>
                  </button>
                </div>
              ) : null}
            </div>

            <button
              type="button"
              disabled={!canCompose}
              onClick={() => {
                setModelMenuOpen(false)
                clearAttachNotice()
                setPlusMenuOpen((open) => !open)
              }}
              className="ds-no-drag inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border border-ds-border bg-ds-card px-3 text-[13px] font-medium text-ds-ink shadow-sm transition hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-50"
              title={t('composerModeSection')}
            >
              <ModeIcon className="h-4 w-4 text-ds-muted" strokeWidth={1.85} />
              <span>{modeLabel}</span>
              <ChevronDown className="h-3.5 w-3.5 text-ds-faint" strokeWidth={1.8} />
            </button>

            <div className="min-w-0 flex-1" />

            <div className="relative min-w-0 shrink-0">
              <button
                type="button"
                disabled={!canChangeModel}
                onClick={() => {
                  setActiveCommand(null)
                  setPlusMenuOpen(false)
                  clearAttachNotice()
                  setModelMenuOpen((open) => !open)
                }}
                className="ds-no-drag inline-flex max-w-[min(100%,280px)] items-center gap-1.5 rounded-full border border-ds-border bg-ds-card px-3 py-1.5 text-[13px] font-medium text-ds-ink shadow-sm transition hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-50"
                title={t('composerModel')}
              >
                <span className="truncate">{activeModelLabel}</span>
                <ChevronDown className="h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.8} />
              </button>
              {modelMenuOpen ? (
                <div className="ds-glass absolute bottom-full right-0 z-40 mb-2 min-w-[180px] overflow-hidden rounded-2xl p-1.5">
                  <div className="px-2 py-1 text-[11px] font-medium uppercase tracking-wide text-ds-faint">
                    {t('composerModelSection')}
                  </div>
                  {modelOptions.map((id) => (
                    <button
                      key={id}
                      type="button"
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => {
                        onComposerModelChange(id)
                        setModelMenuOpen(false)
                        focusComposer()
                      }}
                      className={`flex w-full items-center justify-between gap-2 rounded-xl px-2.5 py-2 text-left text-[13px] transition ${
                        id === activeModelId
                          ? 'bg-accent/10 font-semibold text-ds-ink'
                          : 'text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
                      }`}
                    >
                      <span>{formatComposerModelLabel(id)}</span>
                      {id === activeModelId ? (
                        <span className="text-[11px] text-accent">{t('slashCommandCurrent')}</span>
                      ) : null}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>

            {busy ? (
              <button
                type="button"
                onClick={onInterrupt}
                className="ds-no-drag flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-red-500/45 bg-red-500/15 text-red-600 shadow-sm transition hover:bg-red-500/25 hover:text-red-700 dark:text-red-300 dark:hover:text-red-200"
                aria-label={t('interrupt')}
                title={t('interrupt')}
              >
                <Square className="h-3.5 w-3.5 fill-current" strokeWidth={2.4} />
              </button>
            ) : null}

            <button
              type="button"
              disabled={primaryActionDisabled}
              onClick={handlePrimaryAction}
              className="ds-no-drag flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-accent/15 bg-accent text-white shadow-[0_10px_24px_rgba(79,124,255,0.28)] transition hover:brightness-110 disabled:cursor-not-allowed disabled:border-ds-border disabled:bg-ds-card disabled:text-ds-faint disabled:shadow-none"
              aria-label={primaryActionLabel}
              title={primaryActionLabel}
            >
              <Send className="h-4 w-4" strokeWidth={2.2} />
            </button>
          </div>

          {attachNotice ? (
            <p className="px-2 pb-1 text-[12px] text-amber-700 dark:text-amber-200">{attachNotice}</p>
          ) : null}
        </div>
      </div>
      <div className="mt-2 flex min-h-8 flex-wrap items-center justify-between gap-x-2.5 gap-y-1.5 px-3 sm:px-4">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          <GitBranchPicker workspaceRoot={effectiveWorkspaceRoot} />
          {showThreadUsageFooter ? (
            <div
              className="ds-composer-usage ds-no-drag inline-flex min-h-7 max-w-full min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 overflow-visible rounded-lg border border-ds-border-muted bg-ds-card/72 px-2.5 py-0.5 text-[12.5px] font-medium leading-5 text-ds-muted shadow-sm"
              title={
                threadUsage
                  ? t('sessionUsageDetailsTitle', {
                      tokens: formatCompactNumber(threadUsage.totalTokens),
                      cost: formatCost(threadUsage.costUsd, i18n.language, threadUsage.costCny),
                      saved: formatCompactNumber(threadUsage.tokenEconomySavingsTokens),
                      cache: formatPercent(threadUsage.cacheHitRate),
                      cached: formatCompactNumber(threadUsage.cachedTokens),
                      miss: formatCompactNumber(threadUsage.cacheMissTokens),
                      turns: threadUsage.turns
                    })
                  : t('sessionUsageUnavailable')
              }
            >
              <BarChart3 className="h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.9} />
              {threadUsage ? (
                <>
                  <span className="ds-composer-usage-tokens shrink-0 truncate tabular-nums">
                    {t('sessionUsageTokens', {
                      tokens: formatCompactNumber(threadUsage.totalTokens)
                    })}
                  </span>
                  <span className="text-ds-faint">·</span>
                  <span className="ds-composer-usage-cost shrink-0 truncate tabular-nums">
                    {t('sessionUsageCost', {
                      cost: formatCost(threadUsage.costUsd, i18n.language, threadUsage.costCny)
                    })}
                  </span>
                  {threadUsage.tokenEconomySavingsTokens > 0 ? (
                    <>
                      <span className="text-ds-faint">·</span>
                      <span
                        className="shrink-0 tabular-nums text-emerald-700 dark:text-emerald-300"
                        title={t('sessionUsageContextSavingsTitle', {
                          tokens: formatCompactNumber(threadUsage.tokenEconomySavingsTokens)
                        })}
                      >
                        {t('sessionUsageContextSavings', {
                          tokens: formatCompactNumber(threadUsage.tokenEconomySavingsTokens)
                        })}
                      </span>
                    </>
                  ) : null}
                  <span className="text-ds-faint">·</span>
                  <span className="ds-composer-usage-cache shrink-0 truncate tabular-nums">
                    {t('sessionUsageCache', {
                      cache: formatPercent(threadUsage.cacheHitRate)
                    })}
                  </span>
                  <span className="text-ds-faint">·</span>
                  <span className="ds-composer-usage-turns shrink-0 truncate tabular-nums">
                    {t('sessionUsageTurns', { turns: threadUsage.turns })}
                  </span>
                </>
              ) : (
                <span className="shrink-0 text-ds-faint">
                  {threadUsageState.loading
                    ? t('sessionUsageLoading')
                    : t('sessionUsageUnavailable')}
                </span>
              )}
            </div>
          ) : null}
        </div>
        <ContextUsageMeter
          blocks={blocks}
          model={activeModelId}
          hasActiveThread={hasActiveThread}
          threadId={activeThreadId}
        />
      </div>
      {!runtimeReady ? (
        <p className="px-3 pb-1 text-right text-[11.5px] text-amber-700 dark:text-amber-200 sm:px-4">
          {t('composerOfflineHint')}
        </p>
      ) : !hasActiveThread && !effectiveWorkspaceRoot ? (
        <p className="px-3 pb-1 text-right text-[11.5px] text-ds-faint sm:px-4">{t('composerWorkspaceHint')}</p>
      ) : null}
    </div>
  )
}

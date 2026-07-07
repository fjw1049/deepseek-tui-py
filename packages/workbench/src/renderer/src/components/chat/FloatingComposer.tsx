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
  Bot,
  ChevronDown,
  ChevronRight,
  Clock3,
  FileDiff,
  GitFork,
  ListTodo,
  Loader2,
  MessageCircleQuestion,
  Package,
  Paperclip,
  Plus,
  Plug,
  Search,
  Send,
  Settings2,
  ShieldAlert,
  Shrink,
  Sparkles,
  Square,
  Gauge,
  Mic,
  Wand2,
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
import { resolveActiveThreadWorkspace } from '../../lib/workspace-path'
import { getPetSlashQuery, type PetSlashMenuItem } from '../../lib/pet/pet-slash-commands'
import {
  isUnknownComposerSlashCommand,
  parseComposerActionCommand,
  type ComposerActionCommandId
} from '../../lib/composer-slash-commands'
import { ContextUsageMeter } from './ContextUsageMeter'
import { ComposerCommandPanel } from './ComposerCommandPanel'
import { ComposerVoiceBar, type ComposerVoicePhase } from './ComposerVoiceBar'
import { GitBranchPicker } from './GitBranchPicker'
import {
  joinSpeechText,
  useAudioRecorder,
  type RecordedAudio
} from '../../hooks/use-audio-recorder'
import {
  isComposerVoiceBridgeReady,
  isMediaCaptureSupported,
  loadComposerAsrConfig
} from '../../lib/load-composer-asr-config'

export type ComposerMode = 'plan' | 'agent' | 'ask' | 'workflow'

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
  onNoticeChange?: (notice: string | null) => void
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

function formatAttachmentMention(path: string): string {
  return /\s/.test(path) ? `@"${path}"` : `@${path}`
}

function buildOutboundMessage(attachments: ComposerAttachment[], input: string): string {
  const mentionLines = attachments.map((item) => formatAttachmentMention(item.path))
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
  filterPetSlashCommands,
  onNoticeChange
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const threads = useChatStore((s) => s.threads)
  const blocks = useChatStore((s) => s.blocks)
  const scrollToBlock = useChatStore((s) => s.scrollToBlock)
  const composerModelMeta = useChatStore((s) => s.composerModelMeta)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const shellRef = useRef<HTMLDivElement | null>(null)
  const composingRef = useRef(false)
  const speechBaseRef = useRef('')
  const [voicePhase, setVoicePhase] = useState<ComposerVoicePhase>('idle')
  const [asrConfigured, setAsrConfigured] = useState(false)
  const [focused, setFocused] = useState(false)
  const [plusMenuOpen, setPlusMenuOpen] = useState(false)
  // Which second-level panel the `+` menu is currently revealing on hover.
  const [plusSubmenu, setPlusSubmenu] = useState<'mode' | 'skills' | null>(null)
  const [composerSkills, setComposerSkills] = useState<Array<{ name: string; description?: string }>>([])
  const [skillsLoading, setSkillsLoading] = useState(false)
  const [skillsLoaded, setSkillsLoaded] = useState(false)
  const [skillQuery, setSkillQuery] = useState('')
  const [modelMenuOpen, setModelMenuOpen] = useState(false)
  const [attachNotice, setAttachNotice] = useState<string | null>(null)
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([])
  // Focus-mode skill picked from the `/skills` panel. Held out of the input
  // text (rendered as an inline chip) and prepended as `/name ` only on send,
  // so the runtime's leading-token focus detection still works unchanged.
  const [focusSkill, setFocusSkill] = useState<string | null>(null)
  const [activeCommand, setActiveCommand] = useState<{
    id: ComposerActionCommandId
    args: string
  } | null>(null)
  const effectiveWorkspaceRoot = resolveActiveThreadWorkspace(activeThreadId, threads, workspaceRoot)

  const pendingApprovalCount = countPendingApprovals(blocks)
  const firstPendingApprovalId = blocks.find(
    (block) => block.kind === 'approval' && block.status === 'pending'
  )?.id

  const canCompose = runtimeReady && (hasActiveThread || !!effectiveWorkspaceRoot)
  const canChangeModel = canCompose && !busy
  const outboundPreview = buildOutboundMessage(attachments, input)
  // A picked skill alone is enough to send (the runtime just runs it), even
  // with no typed request yet.
  const canSend = canCompose && (outboundPreview.length > 0 || focusSkill != null)
  const petSlashQuery = getPetSlashQuery(input)
  const slashQuery = petSlashQuery == null ? getSlashQuery(input) : null
  const [selectedCommandIndex, setSelectedCommandIndex] = useState(0)

  const modelOptions = useMemo(
    () => filterComposerModelOptions(composerModel, composerPickList),
    [composerModel, composerPickList]
  )
  const activeModelId = composerModel.trim() || modelOptions[0] || 'deepseek-v4-pro'
  const activeModelLabel = formatComposerModelLabel(activeModelId, composerModelMeta)

  const modeLabel =
    mode === 'plan'
      ? t('composerModePlan')
      : mode === 'ask'
        ? t('composerModeAsk')
        : mode === 'workflow'
          ? t('composerModeWorkflow')
          : t('composerModeAgent')
  const modeBadge = {
    agent: {
      Icon: Bot,
      icon: '#4f7cff',
      gradient: 'linear-gradient(135deg, rgba(79,124,255,0.16), rgba(79,124,255,0.05))',
      border: 'rgba(79,124,255,0.28)'
    },
    plan: {
      Icon: ListTodo,
      icon: '#f59e0b',
      gradient: 'linear-gradient(135deg, rgba(245,158,11,0.18), rgba(245,158,11,0.05))',
      border: 'rgba(245,158,11,0.30)'
    },
    ask: {
      Icon: MessageCircleQuestion,
      icon: '#14b8a6',
      gradient: 'linear-gradient(135deg, rgba(20,184,166,0.18), rgba(20,184,166,0.05))',
      border: 'rgba(20,184,166,0.30)'
    },
    workflow: {
      Icon: Workflow,
      icon: '#8b5cf6',
      gradient: 'linear-gradient(135deg, rgba(139,92,246,0.18), rgba(139,92,246,0.05))',
      border: 'rgba(139,92,246,0.30)'
    }
  }[mode]
  const ModeBadgeIcon = modeBadge.Icon

  const placeholder = !runtimeReady
    ? t('runtimeActionNeedsConnection')
    : !hasActiveThread && !effectiveWorkspaceRoot
      ? t('workspaceRequiredToCreateThread')
      : busy
        ? t('composerQueuePlaceholder')
        : t('composerDefaultPlaceholder')
  const primaryActionDisabled = !canSend || voicePhase !== 'idle'

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

  // Collapse the hovered submenu (and clear the skill filter) whenever the
  // `+` menu closes, so it reopens on the first-level list next time.
  useEffect(() => {
    if (!plusMenuOpen) {
      setPlusSubmenu(null)
      setSkillQuery('')
    }
  }, [plusMenuOpen])

  const loadComposerSkills = useCallback((): void => {
    if (skillsLoaded || skillsLoading) return
    if (!runtimeReady) {
      setSkillsLoaded(true)
      return
    }
    setSkillsLoading(true)
    void window.dsGui
      .runtimeRequest('/v1/skills', 'GET')
      .then((result) => {
        if (result.ok) {
          setComposerSkills((JSON.parse(result.body) as { skills?: typeof composerSkills }).skills ?? [])
        }
      })
      .finally(() => {
        setSkillsLoaded(true)
        setSkillsLoading(false)
      })
  }, [runtimeReady, skillsLoaded, skillsLoading])

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

  const handlePickSkill = (name: string): void => {
    // Hold the skill as an inline chip (not in the input text). The input is
    // cleared so the caret lands at the start, ready for the user's request;
    // `/name ` is prepended only at send time.
    setFocusSkill(name)
    setInput('')
    setActiveCommand(null)
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

  const handleTranscribeRef = useRef<(audio: RecordedAudio | null) => void>(() => {})

  const audioRecorder = useAudioRecorder({
    maxDurationMs: 30_000,
    onAutoStop: (audio) => handleTranscribeRef.current(audio)
  })
  const cancelRecordingRef = useRef(audioRecorder.cancel)
  cancelRecordingRef.current = audioRecorder.cancel
  const stopRecordingRef = useRef(audioRecorder.stop)
  stopRecordingRef.current = audioRecorder.stop
  const startRecordingRef = useRef(audioRecorder.start)
  startRecordingRef.current = audioRecorder.start

  const resetVoiceSession = useCallback((): void => {
    cancelRecordingRef.current()
    setVoicePhase('idle')
  }, [])

  const transcribeRecordedAudio = async (audio: RecordedAudio): Promise<void> => {
    if (typeof window.dsGui === 'undefined' || typeof window.dsGui.transcribeAudio !== 'function') {
      resetVoiceSession()
      setAttachNotice(t('composerVoiceNeedRestart'))
      return
    }
    setVoicePhase('transcribing')
    const buffer = await audio.blob.arrayBuffer()
    const result = await window.dsGui.transcribeAudio({
      audio: buffer,
      mimeType: audio.mimeType,
      fileName: audio.fileName
    })
    resetVoiceSession()
    if (!result.ok) {
      setAttachNotice(result.message)
      return
    }
    setInput(joinSpeechText(speechBaseRef.current, result.text))
    focusComposer()
  }

  const handleTranscribe = (audio: RecordedAudio | null): void => {
    if (!audio) {
      resetVoiceSession()
      setAttachNotice(t('composerVoiceEmpty'))
      return
    }
    void transcribeRecordedAudio(audio)
  }

  handleTranscribeRef.current = handleTranscribe

  const handleStopAndTranscribe = (): void => {
    void stopRecordingRef.current().then((audio) => handleTranscribeRef.current(audio))
  }

  useEffect(() => {
    void loadComposerAsrConfig()
      .then((config) => {
        setAsrConfigured(!!config?.apiKey.trim())
      })
      .catch(() => {
        setAsrConfigured(false)
      })
  }, [])

  useEffect(() => {
    const refreshAsrConfigured = (): void => {
      void loadComposerAsrConfig()
        .then((config) => setAsrConfigured(!!config?.apiKey.trim()))
        .catch(() => setAsrConfigured(false))
    }
    window.addEventListener('focus', refreshAsrConfigured)
    return () => window.removeEventListener('focus', refreshAsrConfigured)
  }, [])

  const handleMicClick = async (): Promise<void> => {
    if (voicePhase !== 'idle') return
    if (!canCompose) return

    if (!isMediaCaptureSupported()) {
      setAttachNotice(t('composerVoiceErrorUnavailable'))
      return
    }

    if (!isComposerVoiceBridgeReady()) {
      setAttachNotice(t('composerVoiceNeedRestart'))
      return
    }

    let config: Awaited<ReturnType<typeof loadComposerAsrConfig>>
    try {
      config = await loadComposerAsrConfig()
    } catch {
      setAttachNotice(t('composerVoiceNeedsKey'))
      return
    }

    const configured = !!config?.apiKey.trim()
    setAsrConfigured(configured)
    if (!configured) {
      setAttachNotice(t('composerVoiceNeedsKey'))
      return
    }

    speechBaseRef.current = input
    setPlusMenuOpen(false)
    setModelMenuOpen(false)
    clearAttachNotice()
    const started = await startRecordingRef.current()
    if (!started.ok) {
      setAttachNotice(
        started.reason === 'denied'
          ? t('composerVoiceErrorNotAllowed')
          : t('composerVoiceErrorDevice')
      )
      return
    }
    setVoicePhase('recording')
  }

  const handleVoiceCancel = (): void => {
    resetVoiceSession()
  }

  const voiceActive = voicePhase !== 'idle'
  const voiceButtonTitle =
    voicePhase === 'recording'
      ? t('composerVoiceConfirm')
      : asrConfigured
        ? t('composerVoiceInput')
        : t('composerVoiceNeedsKey')

  useEffect(() => {
    resetVoiceSession()
  }, [activeThreadId, resetVoiceSession])

  const pickAttachments = async (): Promise<void> => {
    clearAttachNotice()
    if (typeof window.dsGui === 'undefined') {
      setAttachNotice(t('preloadBridgeMissing'))
      return
    }
    if (typeof window.dsGui.pickWorkspaceFiles !== 'function') {
      setAttachNotice(t('composerAttachNeedRestart'))
      return
    }
    const result = await window.dsGui.pickWorkspaceFiles({
      defaultPath: effectiveWorkspaceRoot || undefined,
      workspaceRoot: effectiveWorkspaceRoot || undefined
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

  useEffect(() => {
    onNoticeChange?.(attachNotice)
  }, [attachNotice, onNoticeChange])

  useEffect(() => {
    return () => onNoticeChange?.(null)
  }, [onNoticeChange])

  const handlePrimaryAction = (): void => {
    if (voiceActive) return
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
    const body = buildOutboundMessage(attachments, input)
    // Prepend the focus-mode skill as a leading `/name` token so the runtime
    // detects it (the inline chip is UI-only; the wire format is unchanged).
    const payload = focusSkill ? `/${focusSkill} ${body}`.trim() : body
    if (!payload.trim()) return
    setAttachments([])
    setInput('')
    setFocusSkill(null)
    onSend(payload)
  }

  return (
    <div
      className={`pointer-events-auto w-full ${
        useChatStageWidth ? 'ds-chat-stage px-3 pb-2 pt-0 sm:px-4' : 'max-w-none px-0 pb-2 pt-0'
      } ${stageCentered ? 'shrink-0 pb-1 pt-0' : 'pb-0 pt-1'}`}
    >
      {pendingApprovalCount > 0 ? (
        <div className="mb-2 rounded-[14px] border border-accent/30 bg-[linear-gradient(180deg,rgba(79,124,255,0.08),rgba(79,124,255,0.14))] px-4 py-3 shadow-sm backdrop-blur-xl">
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
        <div className="mb-2 rounded-[14px] border border-ds-border bg-ds-card/88 px-4 py-3 shadow-sm backdrop-blur-xl">
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
            onPickSkill={handlePickSkill}
          />
        ) : (slashQuery != null || petSlashQuery != null) ? (
          <div className="ds-composer-command-popover absolute bottom-full left-[calc(50%-64px)] z-30 flex max-h-[min(420px,50vh)] w-[calc(100%_-_24px)] max-w-[620px] -translate-x-1/2 flex-col overflow-hidden rounded-t-[22px] rounded-b-[14px] p-1.5 shadow-[0_20px_55px_rgba(15,23,42,0.16)]">
            <div className="shrink-0 px-3 pb-1.5 pt-1.5 text-[11px] font-medium uppercase tracking-[0.12em] text-ds-faint">
              {petSlashQuery != null ? t('petSlashCommandMenuTitle') : t('slashCommandMenuTitle')}
            </div>
            {petSlashQuery != null ? (
              filteredPetSlashCommands.length > 0 ? (
                <div className="ds-scroll-surface min-h-0 flex-1 overflow-y-auto">
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
                <div className="rounded-[12px] border border-dashed border-ds-border-muted px-4 py-5 text-[13px] text-ds-faint">
                  {t('slashCommandEmpty')}
                </div>
              )
            ) : filteredSlashCommands.length > 0 ? (
              <div className="ds-scroll-surface min-h-0 flex-1 overflow-y-auto">
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
              <div className="rounded-[12px] border border-dashed border-ds-border-muted px-4 py-5 text-[13px] text-ds-faint">
                {t('slashCommandEmpty')}
              </div>
            )}
            <div className="ds-composer-command-ribbon" aria-hidden />
          </div>
        ) : null}

        <div
          ref={shellRef}
            className={`ds-composer-shell ds-chat-composer ds-frosted flex w-full flex-col px-4 transition sm:px-5 ${
              stageCentered ? 'ds-composer-empty gap-1.5 py-2.5' : 'gap-1.5 py-2.5'
            } ${focused ? 'ds-chat-composer-focus' : ''}`}
        >
          {attachments.length > 0 ? (
            <div className="flex flex-wrap gap-2 px-1 pt-1">
              {attachments.map((item) => (
                <div
                  key={item.id}
                  className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-ds-border-muted bg-ds-main/80 px-2.5 py-1 text-[12px] text-ds-ink"
                >
                  <span className="truncate">@{item.path}</span>
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

          {focusSkill ? (
            <div className="flex flex-wrap gap-2 px-1 pt-1">
              <button
                type="button"
                onClick={() => {
                  setFocusSkill(null)
                  focusComposer()
                }}
                title={t('composerSkillFocus', { name: focusSkill })}
                className="ds-no-drag group inline-flex max-w-full items-center gap-1.5 rounded-full border border-[rgba(79,124,255,0.4)] bg-[rgba(79,124,255,0.14)] px-2.5 py-1 text-[12px] font-medium text-[#4f7cff] transition hover:bg-[rgba(79,124,255,0.22)]"
              >
                <Sparkles className="h-3 w-3 shrink-0" strokeWidth={2} />
                <span className="truncate">{focusSkill}</span>
                <X
                  className="h-3 w-3 shrink-0 opacity-50 transition group-hover:opacity-90"
                  strokeWidth={2}
                />
              </button>
            </div>
          ) : null}

          <textarea
            ref={textareaRef}
            rows={stageCentered ? 1 : 1}
            className={`ds-composer-input ds-no-drag block min-w-0 w-full resize-none break-words bg-transparent px-2 text-ds-ink placeholder:text-ds-faint focus:outline-none [overflow-wrap:anywhere] ${
              stageCentered ? 'min-h-[48px] py-1.5' : 'min-h-[48px] py-1.5'
            } ${canCompose ? '' : 'opacity-80'}`}
            placeholder={placeholder}
            value={input}
            disabled={!canCompose || voicePhase === 'transcribing'}
            onChange={(e) => {
              setInput(e.target.value)
              if (voiceActive) resetVoiceSession()
            }}
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

              if (!composing && e.key === 'Escape' && voiceActive) {
                e.preventDefault()
                resetVoiceSession()
                return
              }
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

          <ComposerVoiceBar
            phase={voicePhase}
            levels={audioRecorder.levels}
            elapsedMs={audioRecorder.elapsedMs}
            maxDurationMs={audioRecorder.maxDurationMs}
            onCancel={handleVoiceCancel}
            labels={{
              recording: t('composerVoiceRecording'),
              transcribing: t('composerVoiceTranscribing'),
              cancel: t('composerVoiceCancel')
            }}
          />

          <div className={`flex items-center gap-2 pl-3 pr-1 ${stageCentered ? 'pb-0' : 'pb-0'}`}>
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
                <div className="absolute bottom-full left-0 z-40 mb-2">
                  <div className="ds-glass min-w-[220px] overflow-hidden rounded-2xl p-1.5">
                    {/* Add files: no submenu, runs immediately. */}
                    <button
                      type="button"
                      disabled={!canCompose}
                      onMouseEnter={() => setPlusSubmenu(null)}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => void pickAttachments()}
                      className="flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-[13px] text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50"
                    >
                      <Paperclip className="h-4 w-4 shrink-0" strokeWidth={1.8} />
                      <span className="flex-1">{t('composerPlusAddFile')}</span>
                    </button>
                    <div className="my-1 border-t border-ds-border-muted" />
                    {/* Mode + Skills: hover previews the submenu, click locks it
                        open so the pointer can travel to the panel and interact
                        with its controls without the panel collapsing. */}
                    <button
                      type="button"
                      onMouseEnter={() => setPlusSubmenu('mode')}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => setPlusSubmenu('mode')}
                      className={`flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-[13px] transition ${
                        plusSubmenu === 'mode'
                          ? 'bg-ds-hover text-ds-ink'
                          : 'text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
                      }`}
                    >
                      <Wand2 className="h-4 w-4 shrink-0" strokeWidth={1.8} />
                      <span className="flex-1">{t('composerPlusMode')}</span>
                      <ChevronRight className="h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.8} />
                    </button>
                    <button
                      type="button"
                      onMouseEnter={() => {
                        setPlusSubmenu('skills')
                        loadComposerSkills()
                      }}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => {
                        setPlusSubmenu('skills')
                        loadComposerSkills()
                      }}
                      className={`flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-[13px] transition ${
                        plusSubmenu === 'skills'
                          ? 'bg-ds-hover text-ds-ink'
                          : 'text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
                      }`}
                    >
                      <Sparkles className="h-4 w-4 shrink-0" strokeWidth={1.8} />
                      <span className="flex-1">{t('composerPlusSkills')}</span>
                      <ChevronRight className="h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.8} />
                    </button>
                  </div>

                  {plusSubmenu === 'mode' ? (
                    <div className="ds-glass absolute bottom-0 left-full ml-2 w-[248px] overflow-hidden rounded-2xl p-2 before:absolute before:inset-y-0 before:-left-2 before:w-2 before:content-['']">
                      <p className="px-1.5 pb-2 pt-1 text-[12px] leading-5 text-ds-faint">
                        {mode === 'plan'
                          ? t('composerModeHintPlan')
                          : mode === 'ask'
                            ? t('composerModeHintAsk')
                            : mode === 'workflow'
                              ? t('composerModeHintWorkflow')
                              : t('composerModeHintDefault')}
                      </p>
                      <div className="border-t border-ds-border-muted pt-1">
                        {(
                          [
                            { id: 'plan' as const, label: t('composerModePlanFull') },
                            { id: 'ask' as const, label: t('composerModeAskFull') },
                            { id: 'workflow' as const, label: t('composerModeWorkflowFull') }
                          ] as const
                        ).map((item) => {
                          const on = mode === item.id
                          return (
                            <button
                              key={item.id}
                              type="button"
                              role="switch"
                              aria-checked={on}
                              onMouseDown={(event) => event.preventDefault()}
                              onClick={() => {
                                clearAttachNotice()
                                setMode(on ? 'agent' : item.id)
                                focusComposer()
                              }}
                              className="flex w-full items-center gap-2 rounded-xl px-1.5 py-2 text-left text-[13px] text-ds-ink transition hover:bg-ds-hover"
                            >
                              <span className="flex-1">{item.label}</span>
                              <span
                                className={`relative inline-flex h-4 w-7 shrink-0 items-center rounded-full transition ${
                                  on ? 'bg-accent' : 'bg-ds-border'
                                }`}
                              >
                                <span
                                  className={`absolute h-3 w-3 rounded-full bg-white shadow-sm transition ${
                                    on ? 'left-[14px]' : 'left-0.5'
                                  }`}
                                />
                              </span>
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  ) : null}

                  {plusSubmenu === 'skills' ? (
                    <div className="ds-glass absolute bottom-0 left-full ml-2 flex max-h-[min(420px,52vh)] w-[300px] flex-col overflow-hidden rounded-2xl p-2 before:absolute before:inset-y-0 before:-left-2 before:w-2 before:content-['']">
                      <div className="mb-2 flex shrink-0 items-center gap-2 rounded-xl border border-ds-border bg-ds-card px-2.5 py-1.5">
                        <Search className="h-4 w-4 shrink-0 text-ds-faint" strokeWidth={1.8} />
                        <input
                          type="text"
                          value={skillQuery}
                          onChange={(event) => setSkillQuery(event.target.value)}
                          placeholder={t('composerSkillSearchPlaceholder')}
                          className="min-w-0 flex-1 bg-transparent text-[13px] text-ds-ink placeholder:text-ds-faint focus:outline-none"
                        />
                      </div>
                      <div className="ds-scroll-surface min-h-0 flex-1 space-y-1 overflow-y-auto">
                        {skillsLoading ? (
                          <div className="flex items-center justify-center px-1.5 py-4 text-ds-faint">
                            <Loader2 className="h-4 w-4 animate-spin" />
                          </div>
                        ) : !runtimeReady ? (
                          <div className="px-1.5 py-3 text-[12px] text-ds-faint">
                            {t('composerSkillsNeedRuntime')}
                          </div>
                        ) : (
                          (() => {
                            const q = skillQuery.trim().toLowerCase()
                            const filtered = composerSkills.filter(
                              (skill) =>
                                !q ||
                                skill.name.toLowerCase().includes(q) ||
                                (skill.description ?? '').toLowerCase().includes(q)
                            )
                            if (filtered.length === 0) {
                              return (
                                <div className="px-1.5 py-3 text-[12px] text-ds-faint">
                                  {t('composerSkillsEmpty')}
                                </div>
                              )
                            }
                            return filtered.map((skill) => (
                              <button
                                key={skill.name}
                                type="button"
                                onMouseDown={(event) => event.preventDefault()}
                                onClick={() => {
                                  handlePickSkill(skill.name)
                                  setPlusMenuOpen(false)
                                }}
                                className="block w-full rounded-xl px-2.5 py-2 text-left transition hover:bg-ds-hover"
                              >
                                <div className="flex items-center gap-2 text-[13px] font-medium text-ds-ink">
                                  <Package className="h-4 w-4 shrink-0" strokeWidth={1.8} />
                                  <span className="truncate">{skill.name}</span>
                                </div>
                                {skill.description ? (
                                  <div className="mt-0.5 line-clamp-2 pl-6 text-[11px] leading-4 text-ds-faint">
                                    {skill.description}
                                  </div>
                                ) : null}
                              </button>
                            ))
                          })()
                        )}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>

            {mode !== 'agent' ? (
              <div
                className="ds-no-drag inline-flex h-8 shrink-0 select-none items-center gap-1.5 text-[13px] font-semibold text-ds-ink"
                title={modeLabel}
              >
                <ModeBadgeIcon
                  className="h-4 w-4 shrink-0"
                  style={{ color: modeBadge.icon }}
                  strokeWidth={2}
                  aria-hidden
                />
                <span>{modeLabel}</span>
              </div>
            ) : null}

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
                <span className="ds-composer-model-label truncate">{activeModelLabel}</span>
                <ChevronDown className="h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.8} />
              </button>
              {modelMenuOpen ? (
                <div className="ds-glass absolute bottom-full right-0 z-40 mb-2 w-max min-w-[220px] max-w-[min(420px,calc(100vw-32px))] overflow-hidden rounded-2xl p-1.5">
                  <div className="flex w-full items-center justify-center px-2 py-1 text-center text-[11px] font-medium uppercase tracking-wide text-ds-faint">
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
                      className={`flex w-full min-w-0 items-center justify-center rounded-xl px-2.5 py-2 text-center text-[13px] font-medium transition ${
                        id === activeModelId
                          ? 'bg-accent/10 text-ds-ink'
                          : 'text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
                      }`}
                    >
                      <span className="ds-composer-model-label truncate whitespace-nowrap">{formatComposerModelLabel(id, composerModelMeta)}</span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>

            {isMediaCaptureSupported() ? (
              <button
                type="button"
                disabled={voicePhase === 'transcribing' || (voicePhase === 'idle' && !canCompose)}
                onClick={() =>
                  voicePhase === 'recording' ? handleStopAndTranscribe() : void handleMicClick()
                }
                aria-label={voiceButtonTitle}
                title={voiceButtonTitle}
                className={`ds-no-drag flex h-9 w-9 shrink-0 items-center justify-center rounded-full border shadow-sm transition disabled:cursor-not-allowed disabled:opacity-50 ${
                  voicePhase === 'recording'
                    ? 'border-red-500/45 bg-red-500/15 text-red-600 hover:bg-red-500/25 dark:text-red-300'
                    : asrConfigured
                      ? 'border-ds-border bg-ds-card text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
                      : 'border-amber-500/35 bg-amber-500/10 text-amber-700 hover:bg-amber-500/15 dark:text-amber-200'
                }`}
              >
                {voicePhase === 'recording' ? (
                  <Square className="h-3.5 w-3.5 fill-current" strokeWidth={2.4} />
                ) : (
                  <Mic className="h-4 w-4" strokeWidth={2} />
                )}
              </button>
            ) : null}

            {busy && !activeHighlightedSlashCommand && voicePhase === 'idle' ? (
              <button
                type="button"
                onClick={onInterrupt}
                className="ds-no-drag flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-red-500/45 bg-red-500/15 text-red-600 shadow-sm transition hover:bg-red-500/25 hover:text-red-700 dark:text-red-300 dark:hover:text-red-200"
                aria-label={t('interrupt')}
                title={t('interrupt')}
              >
                <Square className="h-3.5 w-3.5 fill-current" strokeWidth={2.4} />
              </button>
            ) : (
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
            )}
          </div>
        </div>
      </div>
      <div className="mt-0 grid min-h-6 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-x-2.5 px-3 sm:px-4">
        <div className="min-w-0">
          {stageCentered ? (
            <GitBranchPicker
              key={effectiveWorkspaceRoot}
              workspaceRoot={effectiveWorkspaceRoot}
              usePortal
              menuPlacement="above"
            />
          ) : null}
        </div>
        <span />
        <div className="min-w-0 justify-self-end">
          <ContextUsageMeter
            blocks={blocks}
            model={activeModelId}
            hasActiveThread={hasActiveThread}
            threadId={activeThreadId}
          />
        </div>
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

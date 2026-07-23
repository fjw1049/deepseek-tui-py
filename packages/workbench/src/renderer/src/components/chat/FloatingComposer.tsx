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
  CheckCircle2,
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
  Puzzle,
  Search,
  Send,
  Settings2,
  Shrink,
  Sparkles,
  Square,
  Gauge,
  Mic,
  Trash2,
  Wand2,
  Workflow,
  X
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useChatStore } from '../../store/chat-store'
import { ReasoningEffortSelector } from './ReasoningEffortSelector'
import { ApprovalBubble } from './ApprovalBubble'
import { ComposerLiveChangesHeader } from './ComposerLiveChangesHeader'
import { UserInputBubble } from './UserInputBubble'
import { ComposerApprovalPolicySelector } from './ComposerApprovalPolicySelector'
import {
  filterComposerModelOptions,
  formatComposerModelLabel
} from '../../lib/composer-model-label'
import { decodeModelRef } from '@shared/model-ref'
import { resolveActiveThreadWorkspace } from '../../lib/workspace-path'
import { formatBytes } from '../../lib/format-bytes'
import { getPetSlashQuery, type PetSlashMenuItem } from '../../lib/pet/pet-slash-commands'
import { pluginDisplayTitle, pluginVisual } from '../extensions/plugin-presentation'
import {
  isUnknownComposerSlashCommand,
  parseComposerActionCommand,
  type ComposerActionCommandId
} from '../../lib/composer-slash-commands'
import { ContextUsageMeter } from './ContextUsageMeter'
import { ComposerCommandPanel } from './ComposerCommandPanel'
import { ComposerVoiceBar, type ComposerVoicePhase } from './ComposerVoiceBar'
import { WorkspaceContextBar } from './WorkspaceContextBar'
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
import {
  buildComposerConnectorRows,
  diskServersFromMcpConfig,
  filterComposerConnectorRows,
  mediaConnectorTitle,
  type ComposerConnectorRow,
  type ComposerConnectorSection
} from '../../lib/composer-connectors'

export type ComposerMode = 'plan' | 'agent' | 'ask' | 'workflow'

type ComposerAttachment = {
  id: string
  path: string
  name: string
  size: number
  status: 'uploading' | 'done'
  progress: number
}

type FileBadge = { label: string; className: string }

function fileBasename(path: string): string {
  return path.split(/[/\\]/).filter(Boolean).pop() ?? path
}

// Map a filename to a colored badge by extension. Pure CSS/text — no image
// assets. Colors mirror the rgba style used by the skill/connector chips below.
function fileBadge(name: string): FileBadge {
  const ext = (name.split('.').pop() ?? '').toLowerCase()
  const label = ext ? ext.toUpperCase() : 'FILE'
  const palette: Record<string, string> = {
    green: 'bg-[rgba(16,185,129,0.16)] text-[#059669]',
    red: 'bg-[rgba(239,68,68,0.16)] text-[#dc2626]',
    blue: 'bg-[rgba(59,130,246,0.16)] text-[#2563eb]',
    purple: 'bg-[rgba(139,92,246,0.16)] text-[#7c3aed]',
    slate: 'bg-[rgba(100,116,139,0.16)] text-[#475569]',
    amber: 'bg-[rgba(245,158,11,0.16)] text-[#d97706]'
  }
  const byExt: Record<string, keyof typeof palette> = {
    xlsx: 'green',
    xls: 'green',
    csv: 'green',
    pdf: 'red',
    doc: 'blue',
    docx: 'blue',
    png: 'purple',
    jpg: 'purple',
    jpeg: 'purple',
    gif: 'purple',
    webp: 'purple',
    bmp: 'purple',
    heic: 'purple',
    md: 'slate',
    txt: 'slate',
    js: 'amber',
    ts: 'amber',
    tsx: 'amber',
    jsx: 'amber',
    py: 'amber',
    json: 'amber'
  }
  return { label, className: palette[byExt[ext] ?? 'slate'] }
}

type QueuedComposerMessage = {
  id: string
  text: string
  displayText?: string
  hidden?: boolean
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
  onWithdrawQueuedMessage: (id: string) => QueuedComposerMessage | null
  onSendQueuedMessageNow: (id: string) => void
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
  onWithdrawQueuedMessage,
  onSendQueuedMessageNow,
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
  const { t, i18n } = useTranslation('common')
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const threads = useChatStore((s) => s.threads)
  const blocks = useChatStore((s) => s.blocks)
  const composerModelMeta = useChatStore((s) => s.composerModelMeta)
  const composerReasoningEffort = useChatStore((s) => s.composerReasoningEffort)
  const setComposerReasoningEffort = useChatStore((s) => s.setComposerReasoningEffort)
  const openSettings = useChatStore((s) => s.openSettings)
  // Session-level plugin focus (drives the footer badge) +
  // send action used by the badge exit (× sends `@plugin:off` as a hidden turn).
  const activePlugin = useChatStore((s) => s.activePlugin)
  const pluginLocale = i18n.language
  const displayPluginName = useCallback(
    (id: string | null | undefined): string =>
      id ? pluginDisplayTitle(id, pluginLocale) : '',
    [pluginLocale]
  )
  const sendMessage = useChatStore((s) => s.sendMessage)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const shellRef = useRef<HTMLDivElement | null>(null)
  const composingRef = useRef(false)
  const speechBaseRef = useRef('')
  const [voicePhase, setVoicePhase] = useState<ComposerVoicePhase>('idle')
  const [asrConfigured, setAsrConfigured] = useState(false)
  const [focused, setFocused] = useState(false)
  const [plusMenuOpen, setPlusMenuOpen] = useState(false)
  // Which second-level panel the `+` menu is currently revealing on hover.
  const [plusSubmenu, setPlusSubmenu] = useState<'mode' | 'skills' | 'connectors' | 'plugins' | null>(null)
  const [composerSkills, setComposerSkills] = useState<Array<{ name: string; description?: string }>>([])
  const [skillsLoading, setSkillsLoading] = useState(false)
  const [skillsLoaded, setSkillsLoaded] = useState(false)
  const [skillQuery, setSkillQuery] = useState('')
  // MCP connectors mirror skills: listed from the runtime (so we know live
  // connection state), picked as an inline chip, and prepended as a leading
  // `@name` token on send. ``connected`` drives the green/red status dot.
  const [composerConnectors, setComposerConnectors] = useState<ComposerConnectorRow[]>([])
  const [connectorsLoading, setConnectorsLoading] = useState(false)
  const [connectorsLoaded, setConnectorsLoaded] = useState(false)
  const [connectorQuery, setConnectorQuery] = useState('')
  const [connectorSection, setConnectorSection] = useState<ComposerConnectorSection>('builtin')
  const [attachNotice, setAttachNotice] = useState<string | null>(null)
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([])
  // Simulated-upload interval handles keyed by attachment id, cleared on remove,
  // send, and unmount so no timer fires setState on an unmounted component.
  const attachTimersRef = useRef<Map<string, ReturnType<typeof setInterval>>>(new Map())
  // Focus-mode skill picked from the `/skills` panel. Held out of the input
  // text (rendered as an inline chip) and prepended as `/name ` only on send,
  // so the runtime's leading-token focus detection still works unchanged.
  const [focusSkill, setFocusSkill] = useState<string | null>(null)
  // Focus-mode MCP connector, same lifecycle as focusSkill but prepended as
  // `@name ` on send so the runtime's leading-token connector detection fires.
  const [focusConnector, setFocusConnector] = useState<string | null>(null)
  // Scenario entry: held as an inline chip and prepended as
  // `@plugin:<name> ` on send. After send the chip is cleared and the
  // persistent scenario state arrives from the backend via `activePlugin`.
  const [focusPlugin, setFocusPlugin] = useState<string | null>(null)
  // Plugins list for the `+` > Enter scenario picker (mirrors skills/connectors).
  const [composerPlugins, setComposerPlugins] = useState<
    Array<{ name: string; description?: string; trusted: boolean; enabled: boolean }>
  >([])
  const [pluginsLoading, setPluginsLoading] = useState(false)
  const [pluginsLoaded, setPluginsLoaded] = useState(false)
  const [pluginQuery, setPluginQuery] = useState('')
  const [activeCommand, setActiveCommand] = useState<{
    id: ComposerActionCommandId
    args: string
  } | null>(null)
  const effectiveWorkspaceRoot = resolveActiveThreadWorkspace(activeThreadId, threads, workspaceRoot)

  const pendingApprovals = useMemo(
    () =>
      blocks.filter(
        (block): block is Extract<(typeof blocks)[number], { kind: 'approval' }> =>
          block.kind === 'approval' && block.status === 'pending'
      ),
    [blocks]
  )
  const pendingUserInputs = useMemo(
    () =>
      blocks.filter(
        (block): block is Extract<(typeof blocks)[number], { kind: 'user_input' }> =>
          block.kind === 'user_input' && block.status === 'pending'
      ),
    [blocks]
  )

  const canCompose = runtimeReady && (hasActiveThread || !!effectiveWorkspaceRoot)
  const canChangeModel = canCompose && !busy
  const outboundPreview = buildOutboundMessage(attachments, input)
  // A picked skill alone is enough to send (the runtime just runs it), even
  // with no typed request yet.
  const canSend =
    canCompose &&
    (outboundPreview.length > 0 || focusSkill != null || focusConnector != null || focusPlugin != null)
  const petSlashQuery = getPetSlashQuery(input)
  const slashQuery = petSlashQuery == null ? getSlashQuery(input) : null
  const [selectedCommandIndex, setSelectedCommandIndex] = useState(0)

  const modelOptions = useMemo(
    () => filterComposerModelOptions(composerModel, composerPickList),
    [composerModel, composerPickList]
  )
  const activeModelId = composerModel.trim() || modelOptions[0] || 'deepseek-v4-pro'
  const activeModelLabel = formatComposerModelLabel(activeModelId, composerModelMeta)
  const selectorModels = useMemo(
    () =>
      modelOptions.map((id) => ({
        id,
        label: formatComposerModelLabel(id, composerModelMeta),
        providerId: decodeModelRef(id).providerId
      })),
    [modelOptions, composerModelMeta]
  )

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
    if (!plusMenuOpen) return
    const onPointerDown = (event: MouseEvent): void => {
      const target = event.target
      if (!(target instanceof Node) || !shellRef.current?.contains(target)) {
        setPlusMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [plusMenuOpen])

  // When the runtime transitions from offline→ready, invalidate the cached
  // skills/connectors lists. Without this, a user who opened the `+` menu
  // before the runtime connected would see "no skills" / "no connectors"
  // forever — loadComposerSkills/loadComposerConnectors short-circuit on
  // `skillsLoaded`/`connectorsLoaded` and never re-fetch once the runtime is
  // actually available.
  const prevRuntimeReadyRef = useRef(runtimeReady)
  useEffect(() => {
    const prev = prevRuntimeReadyRef.current
    prevRuntimeReadyRef.current = runtimeReady
    if (!prev && runtimeReady) {
      setSkillsLoaded(false)
      setSkillsLoading(false)
      setComposerSkills([])
      setConnectorsLoaded(false)
      setConnectorsLoading(false)
      setComposerConnectors([])
      setPluginsLoaded(false)
      setPluginsLoading(false)
      setComposerPlugins([])
    }
  }, [runtimeReady])

  // Collapse the hovered submenu (and clear the skill filter) whenever the
  // `+` menu closes, so it reopens on the first-level list next time.
  useEffect(() => {
    if (!plusMenuOpen) {
      setPlusSubmenu(null)
      setSkillQuery('')
      setConnectorQuery('')
      setConnectorSection('builtin')
      setPluginQuery('')
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
        if (!result.ok) return
        try {
          setComposerSkills((JSON.parse(result.body) as { skills?: typeof composerSkills }).skills ?? [])
        } catch {
          // Malformed JSON: leave the list as-is rather than crashing the menu.
        }
      })
      .catch(() => undefined)
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
    setFocusConnector(null)
    setFocusPlugin(null)
    setInput('')
    setActiveCommand(null)
    focusComposer()
  }

  const loadComposerConnectors = useCallback(
    (opts?: { force?: boolean }): void => {
      if (!opts?.force && (connectorsLoaded || connectorsLoading)) return
      setConnectorsLoading(true)

      const loadDisk = async () => {
        if (typeof window.dsGui?.getMcpConfigFile !== 'function') return []
        try {
          const file = await window.dsGui.getMcpConfigFile()
          return diskServersFromMcpConfig(file.content ?? '')
        } catch {
          return []
        }
      }

      const loadRuntime = async () => {
        if (!runtimeReady) return []
        try {
          const result = await window.dsGui.runtimeRequest('/v1/mcp/servers', 'GET')
          if (!result.ok) return []
          const parsed = JSON.parse(result.body) as {
            servers?: Array<{
              name: string
              transport?: string
              connected?: boolean
              enabled?: boolean
              load_policy?: string
              catalog?: string | null
            }>
          }
          return parsed.servers ?? []
        } catch {
          return []
        }
      }

      void Promise.all([loadDisk(), loadRuntime()])
        .then(([diskServers, runtimeServers]) => {
          setComposerConnectors(
            buildComposerConnectorRows({ diskServers, runtimeServers })
          )
        })
        .finally(() => {
          setConnectorsLoaded(true)
          setConnectorsLoading(false)
        })
    },
    [runtimeReady, connectorsLoaded, connectorsLoading]
  )

  const handlePickConnector = (id: string): void => {
    // Mirror handlePickSkill: hold the connector as an inline chip; `@id ` is
    // prepended only at send time. Focus skill/connector are mutually exclusive.
    setFocusConnector(id)
    setFocusSkill(null)
    setFocusPlugin(null)
    setInput('')
    setActiveCommand(null)
    focusComposer()
  }

  const loadComposerPlugins = useCallback((): void => {
    if (pluginsLoaded || pluginsLoading) return
    if (!runtimeReady) {
      setPluginsLoaded(true)
      return
    }
    setPluginsLoading(true)
    const qs = effectiveWorkspaceRoot
      ? `?workspace=${encodeURIComponent(effectiveWorkspaceRoot)}`
      : ''
    void window.dsGui
      .runtimeRequest(`/v1/plugins${qs}`, 'GET')
      .then((result) => {
        if (!result.ok) {
          // Keep pluginsLoaded false so a later open can retry after a blip.
          return
        }
        try {
          const parsed = JSON.parse(result.body) as {
            plugins?: Array<{
              name: string
              description?: string
              enabled?: boolean
              trusted?: boolean
            }>
          }
          setComposerPlugins(
            (parsed.plugins ?? [])
              .filter((p) => p.enabled !== false)
              .map((p) => ({
                name: p.name,
                description: p.description,
                trusted: p.trusted === true,
                enabled: p.enabled !== false
              }))
          )
          setPluginsLoaded(true)
        } catch {
          // Malformed JSON: leave the list as-is; allow retry.
        }
      })
      .catch(() => undefined)
      .finally(() => {
        setPluginsLoading(false)
      })
  }, [runtimeReady, pluginsLoaded, pluginsLoading, effectiveWorkspaceRoot])

  const handlePickPlugin = (name: string): void => {
    // Hold the plugin as an inline chip; `@plugin:<name> ` is prepended only at
    // send time. After send the chip clears and the persistent mount state
    // arrives from the backend via `activePlugin`. Mutually exclusive with
    // skill/connector focus.
    setFocusPlugin(name)
    setFocusSkill(null)
    setFocusConnector(null)
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

  const clearAttachTimer = (id: string): void => {
    const timer = attachTimersRef.current.get(id)
    if (timer !== undefined) {
      clearInterval(timer)
      attachTimersRef.current.delete(id)
    }
  }

  // Drive a card from 0→100% then mark it done. There is no real network
  // upload (attachments are `@path` mentions injected on send); this is a
  // human-friendly progress animation over the file's real byte size. Honors
  // reduced-motion by jumping straight to done.
  const simulateUpload = (id: string): void => {
    // Idempotent: if a timer for this id is already running (e.g. React
    // StrictMode double-invokes the pickAttachments setter path), clear it
    // before starting a new one so we never orphan an interval.
    clearAttachTimer(id)
    const reduceMotion =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduceMotion) {
      setAttachments((prev) =>
        prev.map((item) =>
          item.id === id ? { ...item, progress: 100, status: 'done' } : item
        )
      )
      return
    }
    const stepMs = 90
    const increment = 7
    const timer = setInterval(() => {
      setAttachments((prev) =>
        prev.map((item) => {
          if (item.id !== id || item.status === 'done') return item
          const next = Math.min(100, item.progress + increment)
          if (next >= 100) {
            clearAttachTimer(id)
            return { ...item, progress: 100, status: 'done' }
          }
          return { ...item, progress: next }
        })
      )
    }, stepMs)
    attachTimersRef.current.set(id, timer)
  }

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
    if (result.files.length === 0) return
    // Compute new attachments OUTSIDE the setAttachments updater. Mutating an
    // outer array inside a setState updater is unsafe under React StrictMode
    // (which double-invokes updaters) — it would duplicate ids and cause
    // simulateUpload to register multiple intervals for the same attachment,
    // orphaning timers. Reading `attachments` from the closure is safe here
    // because pickAttachments awaits the modal file picker, so no other
    // attachment mutation can race this point.
    const seen = new Set(attachments.map((item) => item.path))
    const added: string[] = []
    const next: ComposerAttachment[] = [...attachments]
    for (const file of result.files) {
      if (seen.has(file.path)) continue
      seen.add(file.path)
      const id = `att-${file.path}`
      added.push(id)
      next.push({
        id,
        path: file.path,
        name: fileBasename(file.path),
        size: file.size,
        status: 'uploading',
        progress: 0
      })
    }
    if (added.length === 0) {
      setPlusMenuOpen(false)
      focusComposer()
      return
    }
    setAttachments(next)
    for (const id of added) simulateUpload(id)
    setPlusMenuOpen(false)
    focusComposer()
  }

  const removeAttachment = (id: string): void => {
    clearAttachTimer(id)
    setAttachments((prev) => prev.filter((item) => item.id !== id))
  }

  useEffect(() => {
    onNoticeChange?.(attachNotice)
  }, [attachNotice, onNoticeChange])

  useEffect(() => {
    return () => onNoticeChange?.(null)
  }, [onNoticeChange])

  useEffect(() => {
    const timers = attachTimersRef.current
    return () => {
      timers.forEach((timer) => clearInterval(timer))
      timers.clear()
    }
  }, [])

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
    // Prepend the focus target as a leading token so the runtime detects it
    // (chips are UI-only; wire format is unchanged): skill -> `/name`, MCP
    // connector -> `@name`, plugin mount -> `@plugin:name`. Mutually exclusive
    // by construction.
    const payload = focusSkill
      ? `/${focusSkill} ${body}`.trim()
      : focusConnector
        ? `@${focusConnector} ${body}`.trim()
        : focusPlugin
          ? `@plugin:${focusPlugin} ${body}`.trim()
          : body
    if (!payload.trim()) return
    attachTimersRef.current.forEach((timer) => clearInterval(timer))
    attachTimersRef.current.clear()
    setAttachments([])
    setInput('')
    setFocusSkill(null)
    setFocusConnector(null)
    setFocusPlugin(null)
    onSend(payload)
  }

  return (
    <div
      className={`pointer-events-auto w-full ${
        useChatStageWidth ? 'ds-chat-stage px-3 pb-2 pt-0 sm:px-4' : 'max-w-none px-0 pb-2 pt-0'
      } ${stageCentered ? 'shrink-0 pb-1 pt-0' : 'pb-0 pt-1'}`}
    >
      {pendingApprovals.length > 0 || pendingUserInputs.length > 0 ? (
        <div className="ds-no-drag ds-scroll-surface mb-2 max-h-[min(320px,40vh)] space-y-2 overflow-y-auto overscroll-contain">
          {pendingApprovals.map((block) => (
            <ApprovalBubble key={block.id} block={block} />
          ))}
          {pendingUserInputs.map((block) => (
            <UserInputBubble key={block.id} block={block} />
          ))}
        </div>
      ) : null}
      <ComposerLiveChangesHeader
        onReview={() => {
          window.dispatchEvent(new CustomEvent('deepseekgui:open-changes-panel'))
        }}
      />
      {(() => {
        const visibleQueued = queuedMessages.filter((message) => !message.hidden)
        if (visibleQueued.length === 0) return null
        return (
        <div className="mb-2 rounded-[14px] border border-ds-border bg-ds-card/88 px-4 py-3 shadow-sm backdrop-blur-xl">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="inline-flex items-center gap-2 text-[13px] font-medium text-ds-ink">
              <Clock3 className="h-3.5 w-3.5 text-ds-muted" strokeWidth={1.9} />
              <span>{t('queuedMessagesTitle', { count: visibleQueued.length })}</span>
            </div>
            <div className="text-[12px] text-ds-muted">{t('queuedMessagesHint')}</div>
          </div>
          <div className="mt-2 flex flex-col gap-2">
            {visibleQueued.map((message, index) => (
              <div
                key={message.id}
                className="flex min-w-0 max-w-full flex-wrap items-center gap-2 rounded-[12px] border border-ds-border-muted bg-ds-main/80 px-3 py-2 text-[13px] text-ds-ink"
              >
                <span className="shrink-0 text-ds-faint">{index + 1}.</span>
                <span className="min-w-0 flex-1 truncate" title={message.text}>
                  {message.text}
                </span>
                <div className="flex shrink-0 flex-wrap items-center gap-1">
                  <button
                    type="button"
                    onClick={() => onSendQueuedMessageNow(message.id)}
                    className="rounded-full border border-accent/25 bg-accent/10 px-2.5 py-1 text-[12px] font-medium text-accent transition hover:bg-accent/16"
                  >
                    {t('queuedMessageSendNow')}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      const withdrawn = onWithdrawQueuedMessage(message.id)
                      if (!withdrawn) return
                      setInput(withdrawn.displayText?.trim() || withdrawn.text)
                      focusComposer()
                    }}
                    className="rounded-full border border-ds-border-muted px-2.5 py-1 text-[12px] font-medium text-ds-ink transition hover:bg-ds-hover"
                  >
                    {t('queuedMessageWithdraw')}
                  </button>
                  <button
                    type="button"
                    onClick={() => onRemoveQueuedMessage(message.id)}
                    className="rounded-full border border-ds-border-muted px-2.5 py-1 text-[12px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
                    aria-label={t('queuedMessageRemove')}
                    title={t('queuedMessageRemove')}
                  >
                    {t('queuedMessageRemove')}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
        )
      })()}

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
              stageCentered
                ? 'ds-composer-empty relative z-10 gap-1.5 py-2.5'
                : 'gap-1.5 py-2.5'
            } ${focused ? 'ds-chat-composer-focus' : ''}`}
        >
          {attachments.length > 0 ? (
            <div className="flex flex-wrap gap-2 px-1 pt-1">
              {attachments.map((item) => {
                const badge = fileBadge(item.name)
                const uploading = item.status === 'uploading'
                const loaded = Math.round((item.size * item.progress) / 100)
                return (
                  <div
                    key={item.id}
                    className="flex min-w-[200px] max-w-[260px] flex-col gap-1.5 overflow-hidden rounded-[14px] border border-ds-border-muted bg-ds-main/80 px-2.5 py-2"
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] text-[9px] font-semibold tracking-tight ${badge.className}`}
                        aria-hidden
                      >
                        {badge.label}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[12px] font-medium text-ds-ink" title={item.path}>
                          {item.name}
                        </div>
                        <div className="mt-0.5 flex items-center gap-1 text-[11px] text-ds-faint">
                          {uploading ? (
                            <span className="truncate">
                              {t('composerAttachUploading', {
                                percent: item.progress
                              })}
                              {' · '}
                              {formatBytes(loaded)} of {formatBytes(item.size)}
                            </span>
                          ) : (
                            <>
                              <CheckCircle2
                                className="h-3.5 w-3.5 shrink-0 text-[#10b981]"
                                strokeWidth={2}
                              />
                              <span className="truncate">
                                {t('composerAttachCompleted')}
                                {' · '}
                                {formatBytes(item.size)}
                              </span>
                            </>
                          )}
                        </div>
                      </div>
                      {!uploading ? (
                        <button
                          type="button"
                          onClick={() => removeAttachment(item.id)}
                          className="shrink-0 rounded-full p-1 text-ds-faint transition hover:bg-[rgba(239,68,68,0.12)] hover:text-[#dc2626]"
                          aria-label={t('composerAttachmentRemove')}
                        >
                          <Trash2 className="h-3.5 w-3.5" strokeWidth={2} />
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => removeAttachment(item.id)}
                          className="shrink-0 rounded-full p-1 text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
                          aria-label={t('composerAttachmentRemove')}
                        >
                          <X className="h-3.5 w-3.5" strokeWidth={2} />
                        </button>
                      )}
                    </div>
                    {uploading ? (
                      <div className="h-1.5 w-full overflow-hidden rounded-full bg-ds-hover/70">
                        <div
                          className="h-full rounded-full bg-[linear-gradient(90deg,#6366f1,#4f7cff)] transition-[width] duration-150 ease-out"
                          style={{ width: `${item.progress}%` }}
                        />
                      </div>
                    ) : null}
                  </div>
                )
              })}
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

          {focusConnector ? (
            <div className="flex flex-wrap gap-2 px-1 pt-1">
              <button
                type="button"
                onClick={() => {
                  setFocusConnector(null)
                  focusComposer()
                }}
                title={t('composerConnectorFocus', {
                  name: mediaConnectorTitle(focusConnector) ?? focusConnector
                })}
                className="ds-no-drag group inline-flex max-w-full items-center gap-1.5 rounded-full border border-[rgba(16,185,129,0.4)] bg-[rgba(16,185,129,0.14)] px-2.5 py-1 text-[12px] font-medium text-[#10b981] transition hover:bg-[rgba(16,185,129,0.22)]"
              >
                <Plug className="h-3 w-3 shrink-0" strokeWidth={2} />
                <span className="truncate">
                  {mediaConnectorTitle(focusConnector) ?? focusConnector}
                </span>
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
                    <button
                      type="button"
                      onMouseEnter={() => {
                        setPlusSubmenu('connectors')
                        loadComposerConnectors({ force: true })
                      }}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => {
                        setPlusSubmenu('connectors')
                        loadComposerConnectors({ force: true })
                      }}
                      className={`flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-[13px] transition ${
                        plusSubmenu === 'connectors'
                          ? 'bg-ds-hover text-ds-ink'
                          : 'text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
                      }`}
                    >
                      <Plug className="h-4 w-4 shrink-0" strokeWidth={1.8} />
                      <span className="flex-1">{t('composerPlusConnectors')}</span>
                      <ChevronRight className="h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.8} />
                    </button>
                    <button
                      type="button"
                      onMouseEnter={() => {
                        setPlusSubmenu('plugins')
                        loadComposerPlugins()
                      }}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => {
                        setPlusSubmenu('plugins')
                        loadComposerPlugins()
                      }}
                      className={`flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-[13px] transition ${
                        plusSubmenu === 'plugins'
                          ? 'bg-ds-hover text-ds-ink'
                          : 'text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
                      }`}
                    >
                      <Puzzle className="h-4 w-4 shrink-0" strokeWidth={1.8} />
                      <span className="flex-1">{t('composerPlusPlugins')}</span>
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

                  {plusSubmenu === 'connectors' ? (
                    <div className="ds-glass absolute bottom-0 left-full ml-2 flex max-h-[min(420px,52vh)] w-[300px] flex-col overflow-hidden rounded-2xl p-2 before:absolute before:inset-y-0 before:-left-2 before:w-2 before:content-['']">
                      <div className="mb-2 flex shrink-0 gap-1 rounded-xl bg-ds-subtle/70 p-0.5">
                        {(
                          [
                            ['builtin', t('connectorSectionBuiltin')],
                            ['activated', t('connectorSectionActivated')]
                          ] as const
                        ).map(([value, label]) => (
                          <button
                            key={value}
                            type="button"
                            onMouseDown={(event) => event.preventDefault()}
                            onClick={() => setConnectorSection(value)}
                            className={`min-w-0 flex-1 rounded-[10px] px-2 py-1.5 text-[12px] font-semibold transition ${
                              connectorSection === value
                                ? 'bg-ds-card text-ds-ink shadow-sm'
                                : 'text-ds-muted hover:text-ds-ink'
                            }`}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                      <div className="mb-2 flex shrink-0 items-center gap-2 rounded-xl border border-ds-border bg-ds-card px-2.5 py-1.5">
                        <Search className="h-4 w-4 shrink-0 text-ds-faint" strokeWidth={1.8} />
                        <input
                          type="text"
                          value={connectorQuery}
                          onChange={(event) => setConnectorQuery(event.target.value)}
                          placeholder={t('composerConnectorSearchPlaceholder')}
                          className="min-w-0 flex-1 bg-transparent text-[13px] text-ds-ink placeholder:text-ds-faint focus:outline-none"
                        />
                      </div>
                      <div className="ds-scroll-surface min-h-0 flex-1 space-y-1 overflow-y-auto">
                        {connectorsLoading ? (
                          <div className="flex items-center justify-center px-1.5 py-4 text-ds-faint">
                            <Loader2 className="h-4 w-4 animate-spin" />
                          </div>
                        ) : (
                          (() => {
                            const filtered = filterComposerConnectorRows(
                              composerConnectors,
                              connectorSection,
                              connectorQuery
                            )
                            if (filtered.length === 0) {
                              return (
                                <div className="px-1.5 py-3 text-[12px] text-ds-faint">
                                  {connectorSection === 'activated'
                                    ? t('connectorSectionActivatedEmpty')
                                    : !runtimeReady
                                      ? t('composerConnectorsNeedRuntime')
                                      : t('connectorSectionBuiltinEmpty')}
                                </div>
                              )
                            }
                            return filtered.map((connector) => {
                              const selectable = connector.enabled
                              return (
                              <button
                                key={connector.id}
                                type="button"
                                disabled={!selectable}
                                title={
                                  selectable
                                    ? connector.loadPolicy === 'on_focus'
                                      ? t('composerConnectorOnFocusHint')
                                      : undefined
                                    : t('composerConnectorDisconnected', { name: connector.title })
                                }
                                onMouseDown={(event) => event.preventDefault()}
                                onClick={() => {
                                  if (!selectable) return
                                  handlePickConnector(connector.id)
                                  setPlusMenuOpen(false)
                                }}
                                className={`block w-full rounded-xl px-2.5 py-2 text-left transition ${
                                  selectable
                                    ? 'hover:bg-ds-hover'
                                    : 'cursor-not-allowed opacity-40'
                                }`}
                              >
                                <div className="flex items-center gap-2 text-[13px] font-medium text-ds-ink">
                                  <span
                                    className={`h-2 w-2 shrink-0 rounded-full ${
                                      connector.connected
                                        ? 'bg-emerald-500'
                                        : connector.loadPolicy === 'on_focus'
                                          ? 'bg-amber-400'
                                          : 'bg-red-500'
                                    }`}
                                    aria-hidden
                                  />
                                  <Plug className="h-4 w-4 shrink-0" strokeWidth={1.8} />
                                  <span className="truncate">{connector.title}</span>
                                  {connector.loadPolicy === 'on_focus' ? (
                                    <span className="shrink-0 rounded-full bg-ds-subtle px-1.5 py-0.5 text-[10px] font-medium text-ds-muted">
                                      {t('composerConnectorOnFocusHint')}
                                    </span>
                                  ) : null}
                                </div>
                                <div className="mt-0.5 line-clamp-2 pl-[26px] text-[11px] leading-4 text-ds-faint">
                                  {connector.summary || connector.id}
                                </div>
                              </button>
                              )
                            })
                          })()
                        )}
                      </div>
                    </div>
                  ) : null}

                  {plusSubmenu === 'plugins' ? (
                    <div className="ds-glass absolute bottom-0 left-full ml-2 flex max-h-[min(420px,52vh)] w-[300px] flex-col overflow-hidden rounded-2xl p-2 before:absolute before:inset-y-0 before:-left-2 before:w-2 before:content-['']">
                      <div className="mb-2 flex shrink-0 items-center gap-2 rounded-xl border border-ds-border bg-ds-card px-2.5 py-1.5">
                        <Search className="h-4 w-4 shrink-0 text-ds-faint" strokeWidth={1.8} />
                        <input
                          type="text"
                          value={pluginQuery}
                          onChange={(event) => setPluginQuery(event.target.value)}
                          placeholder={t('composerPluginSearchPlaceholder')}
                          className="min-w-0 flex-1 bg-transparent text-[13px] text-ds-ink placeholder:text-ds-faint focus:outline-none"
                        />
                      </div>
                      <div className="ds-scroll-surface min-h-0 flex-1 space-y-1 overflow-y-auto">
                        {pluginsLoading ? (
                          <div className="flex items-center justify-center px-1.5 py-4 text-ds-faint">
                            <Loader2 className="h-4 w-4 animate-spin" />
                          </div>
                        ) : !runtimeReady ? (
                          <div className="px-1.5 py-3 text-[12px] text-ds-faint">
                            {t('composerPluginsNeedRuntime')}
                          </div>
                        ) : (
                          (() => {
                            const q = pluginQuery.trim().toLowerCase()
                            const filtered = composerPlugins.filter((p) => {
                              if (!q) return true
                              const title = displayPluginName(p.name).toLowerCase()
                              return (
                                p.name.toLowerCase().includes(q) ||
                                title.includes(q) ||
                                (p.description ?? '').toLowerCase().includes(q)
                              )
                            })
                            if (filtered.length === 0) {
                              return (
                                <div className="px-1.5 py-3 text-[12px] text-ds-faint">
                                  {t('composerPluginsEmpty')}
                                </div>
                              )
                            }
                            return filtered.map((plugin) => {
                              const alreadyMounted =
                                activePlugin?.name.toLowerCase() === plugin.name.toLowerCase()
                              const visual = pluginVisual(plugin.name)
                              const Icon = visual.icon
                              const title = displayPluginName(plugin.name)
                              return (
                                <button
                                  key={plugin.name}
                                  type="button"
                                  onMouseDown={(event) => event.preventDefault()}
                                  onClick={() => {
                                    handlePickPlugin(plugin.name)
                                    setPlusMenuOpen(false)
                                  }}
                                  className="block w-full rounded-xl px-2.5 py-2 text-left transition hover:bg-ds-hover"
                                >
                                  <div className="flex items-center gap-2 text-[13px] font-medium text-ds-ink">
                                    <span
                                      className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md ${visual.tile}`}
                                    >
                                      <Icon className="h-3.5 w-3.5" strokeWidth={1.9} />
                                    </span>
                                    <span className="min-w-0 flex-1 truncate">
                                      <span className="block truncate">{title}</span>
                                      {title.toLowerCase() !== plugin.name.toLowerCase() ? (
                                        <span className="block truncate font-mono text-[10px] font-normal text-ds-faint">
                                          {plugin.name}
                                        </span>
                                      ) : null}
                                    </span>
                                    {alreadyMounted ? (
                                      <span className="ml-auto shrink-0 rounded-full bg-[rgba(168,85,247,0.16)] px-1.5 py-0.5 text-[10px] font-semibold text-[#a855f7]">
                                        {t('composerPluginActive')}
                                      </span>
                                    ) : (
                                      <span className="ml-auto shrink-0 text-[10px] font-medium text-ds-faint">
                                        {t('composerPluginEnterAction')}
                                      </span>
                                    )}
                                  </div>
                                  {plugin.description ? (
                                    <div className="mt-0.5 line-clamp-2 pl-8 text-[11px] leading-4 text-ds-faint">
                                      {plugin.description}
                                    </div>
                                  ) : null}
                                </button>
                              )
                            })
                          })()
                        )}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>

            <ComposerApprovalPolicySelector
              disabled={!canCompose}
              onOpenChange={(nextOpen) => {
                if (nextOpen) {
                  setPlusMenuOpen(false)
                  setPlusSubmenu(null)
                }
              }}
            />

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

            {activePlugin || focusPlugin ? (
              <div
                className="ds-no-drag group inline-flex h-8 max-w-[min(100%,240px)] shrink-0 select-none items-center gap-1.5 text-[13px] font-semibold text-[#a855f7]"
                title={
                  activePlugin
                    ? t('composerPluginMounted', {
                        name: displayPluginName(activePlugin.name),
                        path: activePlugin.path
                      })
                    : t('composerPluginFocus', { name: displayPluginName(focusPlugin) })
                }
              >
                <Puzzle className="h-4 w-4 shrink-0" strokeWidth={2} aria-hidden />
                <span className="truncate">
                  {activePlugin
                    ? t('composerPluginBadge', { name: displayPluginName(activePlugin.name) })
                    : t('composerPluginPendingBadge', { name: displayPluginName(focusPlugin) })}
                </span>
                <span
                  role="button"
                  tabIndex={0}
                  aria-label={
                    activePlugin
                      ? t('composerPluginUnmount', { name: displayPluginName(activePlugin.name) })
                      : t('composerPluginFocus', { name: displayPluginName(focusPlugin) })
                  }
                  onClick={(event) => {
                    event.stopPropagation()
                    if (activePlugin) {
                      void sendMessage('@plugin:off')
                    } else {
                      setFocusPlugin(null)
                      focusComposer()
                    }
                  }}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      event.stopPropagation()
                      if (activePlugin) {
                        void sendMessage('@plugin:off')
                      } else {
                        setFocusPlugin(null)
                        focusComposer()
                      }
                    }
                  }}
                  className="inline-flex items-center rounded-sm p-0.5 opacity-50 transition hover:bg-[rgba(168,85,247,0.16)] hover:opacity-100"
                >
                  <X className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                </span>
              </div>
            ) : null}

            <div className="min-w-0 flex-1" />

            <ReasoningEffortSelector
              models={selectorModels}
              model={activeModelId}
              onModelChange={(id) => {
                onComposerModelChange(id)
                focusComposer()
              }}
              value={composerReasoningEffort}
              onChange={setComposerReasoningEffort}
              onConfigureModels={() => openSettings('models')}
              disabled={!canChangeModel}
            />

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
                    : 'border-ds-border bg-ds-card text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
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
      {stageCentered ? (
        <WorkspaceContextBar workspaceRoot={effectiveWorkspaceRoot} />
      ) : (
        <div className="mt-0 grid min-h-6 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-x-2.5 px-3 sm:px-4">
          <div className="min-w-0" />
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
      )}
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

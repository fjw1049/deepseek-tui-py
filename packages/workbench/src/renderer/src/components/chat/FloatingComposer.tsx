import { useChatPaneFocused } from './chat-pane-focus'
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement
} from 'react'
import type { Notice, NoticeTone } from '../extensions/marketplace-shared'
import {
  Bot,
  CheckCircle2,
  Clock3,
  FileDiff,
  Flag,
  GitFork,
  ListTodo,
  Loader2,
  MessageCircleQuestion,
  Package,
  Paperclip,
  Plus,
  Plug,
  Puzzle,
  Send,
  Settings2,
  Shrink,
  Sparkles,
  Square,
  Gauge,
  Mic,
  Trash2,
  Wand2,
  X
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useChatStore, useChatStoreApi } from '../../store/chat-store'
import type { ComposerMode } from '../../store/chat-store-types'
import {
  extractTasksFromBlocks,
  isActiveTaskStatus
} from '../../lib/extract-tasks-from-blocks'
import { ReasoningEffortSelector } from './ReasoningEffortSelector'
import { FileChip } from './FileChip'
import { PendingDecisionPanel } from './PendingDecisionPanel'
import { ComposerLiveChangesHeader } from './ComposerLiveChangesHeader'
import { openChangesPanel } from '../../lib/change-review'
import { ComposerApprovalPolicySelector } from './ComposerApprovalPolicySelector'
import {
  filterComposerModelOptions,
  formatComposerModelLabel,
  formatUsageModelName
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
import { ComposerPlusMenu, type ComposerPlusGroup } from './ComposerPlusMenu'
import { ComposerCommandPanel } from './ComposerCommandPanel'
import { ComposerVoiceBar, type ComposerVoicePhase } from './ComposerVoiceBar'
import { WorkspaceContextBar } from './WorkspaceContextBar'
import { PublishConflictBanner } from './PublishConflictBanner'
import {
  joinSpeechText,
  useAudioRecorder,
  type RecordedAudio
} from '../../hooks/use-audio-recorder'
import { useComboboxNav } from '../../hooks/use-combobox-nav'
import { useLightDismiss } from '../../hooks/use-light-dismiss'
import {
  isComposerVoiceBridgeReady,
  isMediaCaptureSupported,
  loadComposerAsrConfig
} from '../../lib/load-composer-asr-config'
import {
  buildComposerConnectorRows,
  composerConnectorDotClass,
  diskServersFromMcpConfig,
  isComposerConnectorSelectable,
  mediaConnectorTitle,
  parseMcpRuntimeServers,
  type ComposerConnectorRow
} from '../../lib/composer-connectors'
import type { PreviewElementPick } from '../../lib/preview-element-picker'
import { previewWorkspaceFile } from '../../lib/workspace-file-preview'
import {
  formatPreviewPickChipLabel,
  formatPreviewPickWireMessage
} from '../../lib/preview-pick-message'
import {
  composerFooterPlanForWidth,
  composerFooterTierForWidth,
  type ComposerFooterTier
} from '../../lib/composer-footer-layout'
import {
  appendComposerSnippet,
  COMPOSER_INSERT_EVENT,
  COMPOSER_RETRY_DRAFT_EVENT,
  formatComposerPathMention,
  queueComposerRetryDraft,
  takeComposerRetryDraft,
  type ComposerInsertDetail,
  WORKSPACE_PATH_DRAG_MIME,
  workspacePathFromDrag
} from '../../lib/composer-insert'
import { isLargePaste } from '../../lib/composer-paste-file'
import { pollWhileVisible } from '../../lib/poll-while-visible'

export type { ComposerMode }

type ComposerAttachment = {
  id: string
  path: string
  name: string
  size: number
  /** Hidden context for the model (e.g. what a browser screenshot shows), sent after the request. */
  contextNote?: string
}

/** An image handed over from another surface (the browser pane), attached like a paste. */
export type IncomingComposerImage = {
  id: number; file: File; contextNote?: (path: string) => string
  /** Told whether the image ended up attached, so the sender can keep its work when it did not. */
  settle?: (attached: boolean) => void
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

const paneAttachments = new Map<string, ComposerAttachment[]>()

type Props = {
  sessionKey?: string
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
  /** Stop also paused the queue; it waits for the user to resume. */
  queuePaused?: boolean
  onResumeQueuedMessages?: () => void
  onSend: (text: string) => Promise<boolean>
  onInterrupt: () => void | Promise<void>
  onCompact: () => Promise<void>
  onFork: () => Promise<void>
  onOpenDiff: () => void
  stageCentered?: boolean
  useChatStageWidth?: boolean
  /** IDE rail: flatter shell, no long “type to send…” placeholder. */
  compactChrome?: boolean
  petSlashCommands?: Array<{
    command: string
    token: string
    title: string
    description: string
    icon: ReactElement
  }>
  onApplyPetSlashCommand?: (command: string) => boolean
  filterPetSlashCommands?: (query: string) => PetSlashMenuItem[]
  onNoticeChange?: (notice: Notice | null) => void
  /** Bump to request focusing the textarea (e.g. after preview element pick). */
  focusRequestId?: number
  /** HTML preview element picks held as chips; JSON context is prepended only on send. */
  previewPicks?: PreviewElementPick[]
  onRemovePreviewPick?: (index: number) => void
  onClearPreviewPicks?: () => void
  incomingImage?: IncomingComposerImage | null
  onIncomingImageConsumed?: (id: number) => void
}

type SlashCommandId = ComposerMode | ComposerActionCommandId | 'goal'

type SlashCommand = {
  id: SlashCommandId
  kind: 'mode' | 'action' | 'insert'
  title: string
  description: string
  keywords: string[]
  icon: ReactElement
  insertText?: string
}

type PetSlashCommandView = NonNullable<Props['petSlashCommands']>[number]

function getSlashQuery(input: string): string | null {
  const trimmed = input.trimStart()
  if (!trimmed.startsWith('/')) return null
  if (/\s/.test(trimmed)) return null
  return trimmed.slice(1).toLowerCase()
}

function buildOutboundMessage(attachments: ComposerAttachment[], input: string): string {
  const mentionLines = attachments.map((item) => formatComposerPathMention(item.path))
  const notes = attachments.flatMap((item) => item.contextNote ? [item.contextNote] : [])
  return [...mentionLines, input.trim(), ...notes].filter(Boolean).join('\n')
}

export function FloatingComposer({
  sessionKey,
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
  queuePaused = false,
  onResumeQueuedMessages,
  onSend,
  onInterrupt,
  onCompact,
  onFork,
  onOpenDiff,
  useChatStageWidth = true,
  compactChrome = false,
  petSlashCommands = [],
  onApplyPetSlashCommand,
  filterPetSlashCommands,
  onNoticeChange,
  focusRequestId = 0,
  previewPicks = [],
  onRemovePreviewPick,
  onClearPreviewPicks,
  incomingImage = null,
  onIncomingImageConsumed
}: Props): ReactElement {
  const paneFocused = useChatPaneFocused()
  const chatStore = useChatStoreApi()
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
  const currentGoal = useChatStore((s) => s.currentGoal)
  const pluginLocale = i18n.language
  const displayPluginName = useCallback(
    (id: string | null | undefined): string =>
      id ? pluginDisplayTitle(id, pluginLocale) : '',
    [pluginLocale]
  )
  const sendMessage = useChatStore((s) => s.sendMessage)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const inputRef = useRef(input)
  inputRef.current = input
  const activeThreadIdRef = useRef(activeThreadId)
  activeThreadIdRef.current = activeThreadId
  const previewPicksRef = useRef(previewPicks)
  previewPicksRef.current = previewPicks
  const mountedRef = useRef(true)
  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])
  const shellRef = useRef<HTMLDivElement | null>(null)
  const footerRef = useRef<HTMLDivElement | null>(null)
  const plusMenuRef = useRef<HTMLDivElement | null>(null)
  const plusPanelRef = useRef<HTMLDivElement | null>(null)
  const [footerWidth, setFooterWidth] = useState<number | null>(null)
  const composingRef = useRef(false)
  const lastSendClickAtRef = useRef(0)
  const interruptRequestRef = useRef<symbol | null>(null)
  const [interruptPending, setInterruptPending] = useState(false)
  useEffect(() => {
    interruptRequestRef.current = null
    setInterruptPending(false)
  }, [activeThreadId, busy])
  const speechBaseRef = useRef('')
  const voiceRequestId = useRef(0)
  const [voicePhase, setVoicePhase] = useState<ComposerVoicePhase>('idle')
  const [asrConfigured, setAsrConfigured] = useState(false)
  const [focused, setFocused] = useState(false)
  const [plusMenuOpen, setPlusMenuOpen] = useState(false)
  const [composerSkills, setComposerSkills] = useState<Array<{ name: string; description?: string }>>([])
  const [skillsLoading, setSkillsLoading] = useState(false)
  const [skillsLoaded, setSkillsLoaded] = useState(false)
  // MCP connectors mirror skills: listed from the runtime (so we know live
  // connection state), picked as an inline chip, and prepended as a leading
  // `@name` token on send. ``connected`` drives the green/red status dot.
  const [composerConnectors, setComposerConnectors] = useState<ComposerConnectorRow[]>([])
  const [connectorsLoading, setConnectorsLoading] = useState(false)
  const [connectorsLoaded, setConnectorsLoaded] = useState(false)
  const [attachNotice, setAttachNotice] = useState<Notice | null>(null)
  const [attachments, setAttachments] = useState<ComposerAttachment[]>(() => sessionKey ? paneAttachments.get(sessionKey) ?? [] : [])
  const attachmentSessionRef = useRef(sessionKey)
  useEffect(() => {
    if (attachmentSessionRef.current !== sessionKey) {
      if (attachmentSessionRef.current) paneAttachments.set(attachmentSessionRef.current, attachments)
      attachmentSessionRef.current = sessionKey
      setAttachments(sessionKey ? paneAttachments.get(sessionKey) ?? [] : [])
      return
    }
    if (sessionKey) paneAttachments.set(sessionKey, attachments)
  }, [sessionKey, attachments])
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
  const pendingPluginSelection = useChatStore(s => s.pendingPluginSelection)
  useEffect(() => {
    if (!pendingPluginSelection || !paneFocused) return
    setFocusPlugin(pendingPluginSelection)
    setFocusSkill(null)
    setFocusConnector(null)
    useChatStore.setState({ pendingPluginSelection: null })
    textareaRef.current?.focus()
  }, [pendingPluginSelection, paneFocused])

  const footerLayoutOpts = useMemo(
    () => ({
      dense: compactChrome,
      hasMode: mode !== 'agent',
      hasPlugin: Boolean(activePlugin || focusPlugin)
    }),
    [activePlugin, compactChrome, focusPlugin, mode]
  )
  const footerTier = useMemo(
    () => composerFooterTierForWidth(footerWidth, footerLayoutOpts),
    [footerWidth, footerLayoutOpts]
  )
  const footerPlan = useMemo(
    () => composerFooterPlanForWidth(footerWidth, footerLayoutOpts),
    [footerWidth, footerLayoutOpts]
  )
  // Plugins list for the `+` > Enter scenario picker (mirrors skills/connectors).
  const [composerPlugins, setComposerPlugins] = useState<
    Array<{ name: string; description?: string; trusted: boolean; enabled: boolean }>
  >([])
  const [pluginsLoading, setPluginsLoading] = useState(false)
  const [pluginsLoaded, setPluginsLoaded] = useState(false)
  const [activeCommand, setActiveCommand] = useState<{
    id: ComposerActionCommandId
    args: string
  } | null>(null)
  const effectiveWorkspaceRoot = resolveActiveThreadWorkspace(activeThreadId, threads, workspaceRoot)
  const activePublishThread = activeThreadId
    ? threads.find((thread) => thread.id === activeThreadId)
    : undefined
  const activeThreadPublishUnresolved = Boolean(
    activePublishThread?.publishBlocked ||
      activePublishThread?.publishPending ||
      activePublishThread?.publishRequestAction
  )

  const pendingUserInputs = useMemo(
    () =>
      blocks.filter(
        (block): block is Extract<(typeof blocks)[number], { kind: 'user_input' }> =>
          block.kind === 'user_input' && block.status === 'pending'
      ),
    [blocks]
  )
  const hasActiveDurableTask = useMemo(
    () => extractTasksFromBlocks(blocks).some((task) => isActiveTaskStatus(task.status)),
    [blocks]
  )
  const refreshPendingUserInputs = useChatStore((s) => s.refreshPendingUserInputs)

  const [imageImports, setImageImports] = useState(0)
  const imageTargetRef = useRef('')
  imageTargetRef.current = `${activeThreadId ?? ""}:${effectiveWorkspaceRoot}`
  const canCompose = runtimeReady && (hasActiveThread || !!effectiveWorkspaceRoot)
  const canChangeModel = canCompose && !busy
  const outboundPreview = buildOutboundMessage(attachments, input)
  // A picked skill alone is enough to send (the runtime just runs it), even
  // with no typed request yet.
  const canSend =
    canCompose &&
    imageImports === 0 &&
    !activeThreadPublishUnresolved &&
    (outboundPreview.length > 0 ||
      focusSkill != null ||
      focusConnector != null ||
      focusPlugin != null ||
      previewPicks.length > 0)
  const petSlashQuery = getPetSlashQuery(input)
  const slashQuery = petSlashQuery == null ? getSlashQuery(input) : null
  const [selectedCommandIndex, setSelectedCommandIndex] = useState(0)

  const modelOptions = useMemo(
    () => filterComposerModelOptions(composerModel, composerPickList),
    [composerModel, composerPickList]
  )
  const activeModelId = composerModel.trim() || modelOptions[0] || ''
  const activeModelLabel = formatComposerModelLabel(activeModelId, composerModelMeta)
  const selectorModels = useMemo(
    () =>
      modelOptions.map((id) => ({
        id,
        label: formatComposerModelLabel(id, composerModelMeta),
        compactLabel: formatUsageModelName(id, composerModelMeta),
        providerId: decodeModelRef(id).providerId
      })),
    [modelOptions, composerModelMeta]
  )

  const modeLabel =
    mode === 'plan'
      ? t('composerModePlan')
      : mode === 'ask'
        ? t('composerModeAsk')
        : mode === 'goal'
          ? t('composerModeGoal')
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
    goal: {
      Icon: Flag,
      icon: '#f43f5e',
      gradient: 'linear-gradient(135deg, rgba(244,63,94,0.18), rgba(244,63,94,0.05))',
      border: 'rgba(244,63,94,0.30)'
    }
  }[mode]
  const ModeBadgeIcon = modeBadge.Icon

  const placeholder = !runtimeReady
    ? t('runtimeActionNeedsConnection')
    : !hasActiveThread && !effectiveWorkspaceRoot
      ? t('workspaceRequiredToCreateThread')
      : busy
        ? t('composerQueuePlaceholder')
        : mode === 'goal' && !currentGoal
          ? t('composerGoalPlaceholder')
        : ''
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
        id: 'goal',
        kind: 'mode',
        title: t('slashCommandGoalTitle'),
        description:
          mode === 'goal'
            ? t('slashCommandGoalActiveDescription')
            : t('slashCommandGoalDescription'),
        keywords: ['goal', 'objective', '目标'],
        icon: <Flag className="h-4 w-4" strokeWidth={1.9} />
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

  // Soft grow via height:auto. Empty value must NOT follow placeholder
  // scrollHeight — narrow columns wrap the long CJK placeholder into a tall box.
  const resizeTextarea = useCallback(() => {
    const el = textareaRef.current
    if (!el) return
    const minHeight = compactChrome ? 22 : 48
    const maxHeight = compactChrome ? 120 : 176
    if (!el.value) {
      el.style.height = `${minHeight}px`
      el.style.overflowY = 'hidden'
      return
    }
    el.style.height = 'auto'
    const nextHeight = Math.min(Math.max(el.scrollHeight, minHeight), maxHeight)
    el.style.height = `${nextHeight}px`
    el.style.overflowY = el.scrollHeight > maxHeight ? 'auto' : 'hidden'
  }, [compactChrome])

  useLayoutEffect(() => {
    resizeTextarea()
  }, [attachments.length, canCompose, input, resizeTextarea])

  // Re-clamp when the composer column width changes (sidebar drag / restore).
  useEffect(() => {
    const el = textareaRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => {
      resizeTextarea()
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [resizeTextarea])

  useEffect(() => {
    setActiveCommand(null)
  }, [activeThreadId])

  // Bridged task consent is not a TurnItem; re-hydrate after thread switches and
  // keep polling while a durable task is still running (SSE can race turn-complete).
  useEffect(() => {
    if (!activeThreadId || !runtimeReady) return
    void refreshPendingUserInputs()
  }, [activeThreadId, runtimeReady, refreshPendingUserInputs])

  useEffect(() => {
    if (!activeThreadId || !runtimeReady || !hasActiveDurableTask) return
    if (pendingUserInputs.length > 0) return
    return pollWhileVisible(() => {
      void refreshPendingUserInputs()
    }, 2000)
  }, [
    activeThreadId,
    runtimeReady,
    hasActiveDurableTask,
    pendingUserInputs.length,
    refreshPendingUserInputs
  ])

  useEffect(() => {
    const el = footerRef.current
    if (!el || typeof ResizeObserver === 'undefined') return

    let frame = 0
    const apply = (width: number): void => {
      setFooterWidth(width)
    }
    apply(el.getBoundingClientRect().width)
    const observer = new ResizeObserver(([entry]) => {
      const nextWidth = entry?.contentRect.width ?? el.getBoundingClientRect().width
      window.cancelAnimationFrame(frame)
      frame = window.requestAnimationFrame(() => apply(nextWidth))
    })
    observer.observe(el)
    return () => {
      window.cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [])

  useEffect(() => {
    setSelectedCommandIndex(0)
  }, [petSlashQuery, slashQuery])

  useLightDismiss({
    open: plusMenuOpen,
    onDismiss: () => setPlusMenuOpen(false),
    refs: [plusMenuRef, plusPanelRef]
  })

  useEffect(() => {
    const shell = shellRef.current
    if (!shell) return
    const onOpen = (): void => {
      shell.classList.add('ds-composer-model-picker-open')
    }
    const onClose = (): void => {
      shell.classList.remove('ds-composer-model-picker-open')
    }
    shell.addEventListener('model-picker-open', onOpen)
    shell.addEventListener('model-picker-close', onClose)
    return () => {
      shell.removeEventListener('model-picker-open', onOpen)
      shell.removeEventListener('model-picker-close', onClose)
      shell.classList.remove('ds-composer-model-picker-open')
    }
  }, [])

  const menuLoadGeneration = useRef(0)

  useEffect(() => {
    if (!footerPlan.showPlus && plusMenuOpen) {
      setPlusMenuOpen(false)
    }
  }, [footerPlan.showPlus, plusMenuOpen])

  const loadComposerSkills = useCallback((force = false): void => {
    if (!force && (skillsLoaded || skillsLoading)) return
    const generation = menuLoadGeneration.current
    if (!runtimeReady) {
      setSkillsLoaded(true)
      return
    }
    setSkillsLoading(true)
    void window.dsGui
      .runtimeRequest('/v1/skills', 'GET')
      .then((result) => {
        if (generation !== menuLoadGeneration.current || !result.ok) return
        try {
          setComposerSkills((JSON.parse(result.body) as { skills?: typeof composerSkills }).skills ?? [])
          setSkillsLoaded(true)
        } catch {
          // Malformed JSON: leave the list as-is rather than crashing the menu.
        }
      })
      .catch(() => undefined)
      .finally(() => {
        if (generation !== menuLoadGeneration.current) return
        setSkillsLoading(false)
      })
  }, [runtimeReady, skillsLoaded, skillsLoading])

  const focusComposer = (): void => {
    window.requestAnimationFrame(() => textareaRef.current?.focus())
  }

  const restoreRetryDraft = useCallback((): void => {
    if (!activeThreadId || inputRef.current.trim()) return
    const draft = takeComposerRetryDraft(activeThreadId)
    if (!draft) return
    setInput(draft)
    if (paneFocused) window.requestAnimationFrame(() => textareaRef.current?.focus())
  }, [activeThreadId, setInput, paneFocused])

  useEffect(() => {
    if (!focusRequestId) return
    focusComposer()
  }, [focusRequestId])

  useEffect(() => {
    const onInsert = (event: Event): void => {
      const detail = (event as CustomEvent<ComposerInsertDetail>).detail
      if (detail?.threadId ? detail.threadId !== activeThreadId : !paneFocused) return
      const text = detail?.text
      if (typeof text !== 'string' || !text.trim()) return
      setInput(appendComposerSnippet(inputRef.current, text))
      focusComposer()
    }
    window.addEventListener(COMPOSER_INSERT_EVENT, onInsert)
    return () => window.removeEventListener(COMPOSER_INSERT_EVENT, onInsert)
  }, [setInput, paneFocused, activeThreadId])

  useEffect(() => {
    restoreRetryDraft()
    window.addEventListener(COMPOSER_RETRY_DRAFT_EVENT, restoreRetryDraft)
    return () => window.removeEventListener(COMPOSER_RETRY_DRAFT_EVENT, restoreRetryDraft)
  }, [input, restoreRetryDraft])

  const applySlashCommand = (command: SlashCommand): void => {
    if (command.kind === 'insert') {
      setInput(command.insertText ?? `/${command.id} `)
      focusComposer()
      return
    }
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

  const connectorsInFlight = useRef(false)
  const loadComposerConnectors = useCallback(
    (opts?: { force?: boolean }): void => {
      if (connectorsInFlight.current || (!opts?.force && connectorsLoaded)) return
      connectorsInFlight.current = true
      const generation = menuLoadGeneration.current
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
          return parseMcpRuntimeServers(result.body)
        } catch {
          return []
        }
      }

      void Promise.all([loadDisk(), loadRuntime()])
        .then(([diskServers, runtimeServers]) => {
          if (generation !== menuLoadGeneration.current) return
          setComposerConnectors(
            buildComposerConnectorRows({ diskServers, runtimeServers })
          )
        })
        .finally(() => {
          if (generation !== menuLoadGeneration.current) return
          connectorsInFlight.current = false
          setConnectorsLoaded(true)
          setConnectorsLoading(false)
        })
    },
    [runtimeReady, connectorsLoaded]
  )

  useEffect(() => {
    if (!plusMenuOpen) return
    const pending = composerConnectors.some((connector) => connector.status === 'connecting')
    if (!pending) return
    return pollWhileVisible(() => loadComposerConnectors({ force: true }), 1500)
  }, [plusMenuOpen, composerConnectors, loadComposerConnectors])

  useEffect(() => {
    if (!focusConnector || !connectorsLoaded) return
    const row = composerConnectors.find((connector) => connector.id === focusConnector)
    if (row && !isComposerConnectorSelectable(row)) {
      setFocusConnector(null)
    }
  }, [focusConnector, composerConnectors, connectorsLoaded])

  const handlePickConnector = (id: string): void => {
    const row = composerConnectors.find((connector) => connector.id === id)
    if (row && !isComposerConnectorSelectable(row)) return
    // Mirror handlePickSkill: hold the connector as an inline chip; `@id ` is
    // prepended only at send time. Focus skill/connector are mutually exclusive.
    setFocusConnector(id)
    setFocusSkill(null)
    setFocusPlugin(null)
    setInput('')
    setActiveCommand(null)
    focusComposer()
  }

  const loadComposerPlugins = useCallback((force = false): void => {
    if (!force && (pluginsLoaded || pluginsLoading)) return
    const generation = menuLoadGeneration.current
    if (!runtimeReady) {
      setPluginsLoaded(true)
      return
    }
    setPluginsLoading(true)
    const qs = effectiveWorkspaceRoot
      ? `?workspace=${encodeURIComponent(effectiveWorkspaceRoot)}`
      : ''
    void Promise.all([
      window.dsGui.runtimeRequest(`/v1/plugins${qs}`, 'GET'),
      window.dsGui.runtimeRequest('/v1/cua/status', 'GET').then(result => {
        if (!result.ok) return false
        const status = JSON.parse(result.body)
        return status?.supported === true && status.installed === true && status.enabled === true
      }).catch(() => false)
    ])
      .then(([result, cuaAvailable]) => {
        if (generation !== menuLoadGeneration.current) return
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
            [
              ...(cuaAvailable ? [{ name: 'computer-use', description: t('computerUseSummary'), trusted: true, enabled: true }] : []),
              ...(parsed.plugins ?? [])
            ]
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
        if (generation !== menuLoadGeneration.current) return
        setPluginsLoading(false)
      })
  }, [runtimeReady, pluginsLoaded, pluginsLoading, effectiveWorkspaceRoot, t])

  const preloadedMenuScope = useRef<string | null>(null)
  useEffect(() => {
    const scope = runtimeReady ? (effectiveWorkspaceRoot ?? '') : null
    if (preloadedMenuScope.current === scope) return
    preloadedMenuScope.current = scope
    // Ignore responses from a previous workspace or runtime connection.
    menuLoadGeneration.current += 1
    connectorsInFlight.current = false
    setComposerSkills([])
    setComposerPlugins([])
    setComposerConnectors([])
    setSkillsLoaded(false)
    setPluginsLoaded(false)
    setConnectorsLoaded(false)
    setSkillsLoading(false)
    setPluginsLoading(false)
    setConnectorsLoading(false)
    if (!runtimeReady) return
    loadComposerSkills(true)
    loadComposerPlugins(true)
    loadComposerConnectors({ force: true })
  }, [runtimeReady, effectiveWorkspaceRoot, loadComposerSkills, loadComposerPlugins, loadComposerConnectors])

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

  const showAttachNotice = (message: string, tone: NoticeTone = 'error'): void => {
    setAttachNotice({ message, tone })
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
    voiceRequestId.current += 1
    cancelRecordingRef.current()
    setVoicePhase('idle')
  }, [])

  const transcribeRecordedAudio = async (audio: RecordedAudio): Promise<void> => {
    if (typeof window.dsGui === 'undefined' || typeof window.dsGui.transcribeAudio !== 'function') {
      resetVoiceSession()
      showAttachNotice(t('composerVoiceNeedRestart'), 'info')
      return
    }
    setVoicePhase('transcribing')
    const requestId = ++voiceRequestId.current
    let timeout: number | undefined
    try {
      const buffer = await audio.blob.arrayBuffer()
      const result = await Promise.race([
        window.dsGui.transcribeAudio({
          audio: buffer,
          mimeType: audio.mimeType,
          fileName: audio.fileName
        }),
        new Promise<never>((_, reject) => {
          timeout = window.setTimeout(() => reject(new Error('transcription timeout')), 90_000)
        })
      ])
      if (requestId !== voiceRequestId.current) return
      if (!result.ok) {
        showAttachNotice(result.message)
        return
      }
      setInput(joinSpeechText(speechBaseRef.current, result.text))
      focusComposer()
    } catch {
      if (requestId === voiceRequestId.current) showAttachNotice(t('composerVoiceTranscriptionFailed'))
    } finally {
      if (timeout !== undefined) window.clearTimeout(timeout)
      if (requestId === voiceRequestId.current) resetVoiceSession()
    }
  }

  const handleTranscribe = (audio: RecordedAudio | null): void => {
    if (!audio) {
      resetVoiceSession()
      showAttachNotice(t('composerVoiceEmpty'))
      return
    }
    void transcribeRecordedAudio(audio)
  }

  handleTranscribeRef.current = handleTranscribe

  const handleStopAndTranscribe = (): void => {
    void stopRecordingRef.current()
      .then((audio) => handleTranscribeRef.current(audio))
      .catch(() => {
        resetVoiceSession()
        showAttachNotice(t('composerVoiceTranscriptionFailed'))
      })
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
      showAttachNotice(t('composerVoiceErrorUnavailable'))
      return
    }

    if (!isComposerVoiceBridgeReady()) {
      showAttachNotice(t('composerVoiceNeedRestart'), 'info')
      return
    }

    let config: Awaited<ReturnType<typeof loadComposerAsrConfig>>
    try {
      config = await loadComposerAsrConfig()
    } catch {
      showAttachNotice(t('composerVoiceNeedsKey'), 'info')
      return
    }

    const configured = !!config?.apiKey.trim()
    setAsrConfigured(configured)
    if (!configured) {
      showAttachNotice(t('composerVoiceNeedsKey'), 'info')
      return
    }

    speechBaseRef.current = input
    setPlusMenuOpen(false)
    clearAttachNotice()
    const started = await startRecordingRef.current()
    if (!started.ok) {
      showAttachNotice(
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
      showAttachNotice(t('preloadBridgeMissing'), 'info')
      return
    }
    if (typeof window.dsGui.pickWorkspaceFiles !== 'function') {
      showAttachNotice(t('composerAttachNeedRestart'), 'info')
      return
    }
    const result = await window.dsGui.pickWorkspaceFiles({
      defaultPath: effectiveWorkspaceRoot || undefined,
      workspaceRoot: effectiveWorkspaceRoot || undefined
    })
    if (!result.ok) {
      showAttachNotice(result.message ?? t('composerAttachFailed'))
      return
    }
    if (result.files.length === 0) return
    // Compute new attachments OUTSIDE the setAttachments updater. Mutating an
    // outer array inside a setState updater is unsafe under React StrictMode
    // (which double-invokes updaters) — it would duplicate ids. Reading
    // `attachments` from the closure is safe here
    // because pickAttachments awaits the modal file picker, so no other
    // attachment mutation can race this point.
    const seen = new Set(attachments.map((item) => item.path))
    const next: ComposerAttachment[] = [...attachments]
    for (const file of result.files) {
      if (seen.has(file.path)) continue
      seen.add(file.path)
      const id = `att-${file.path}`
      next.push({
        id,
        path: file.path,
        name: fileBasename(file.path),
        size: file.size
      })
    }
    if (next.length === attachments.length) {
      setPlusMenuOpen(false)
      focusComposer()
      return
    }
    setAttachments(next)
    setPlusMenuOpen(false)
    focusComposer()
  }

  const insertTextAtCursor = (text: string): void => {
    const el = textareaRef.current
    const current = inputRef.current
    if (!el) {
      setInput(appendComposerSnippet(current, text))
      return
    }
    const start = el.selectionStart
    const end = el.selectionEnd
    setInput(`${current.slice(0, start)}${text}${current.slice(end)}`)
  }

  /** Resolves true only when every file was attached. */
  const attachImageFiles = async (files: File[], contextNote?: (path: string) => string): Promise<boolean> => {
    if (!canCompose || !effectiveWorkspaceRoot || !files.length) return false
    const target = imageTargetRef.current
    setImageImports((count) => count + 1)
    try {
      if (typeof window.dsGui?.writePasteImageFile !== 'function') throw new Error(t('composerPasteNeedRestart'))
      for (const file of files) {
        if (file.size > 32 * 1024 * 1024) throw new Error(t('composerImageTooLarge'))
        const dataUrl = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader()
          reader.onload = () => resolve(String(reader.result))
          reader.onerror = () => reject(new Error(t('composerPasteFailed')))
          reader.readAsDataURL(file)
        })
        if (target !== imageTargetRef.current) return false
        const result = await window.dsGui.writePasteImageFile({ workspaceRoot: effectiveWorkspaceRoot, dataUrl })
        if (!result.ok) throw new Error(result.message)
        if (target !== imageTargetRef.current) return false
        setAttachments((previous) => [...previous, {
          id: `att-${result.relativePath}`, path: result.relativePath, name: file.name || result.name,
          size: result.size, ...(contextNote ? { contextNote: contextNote(result.relativePath) } : {})
        }])
      }
      focusComposer()
      return true
    } catch (error) {
      if (target === imageTargetRef.current) showAttachNotice(error instanceof Error ? error.message : t('composerPasteFailed'))
      return false
    } finally {
      setImageImports((count) => count - 1)
    }
  }

  const handledIncomingImage = useRef(0)
  useEffect(() => {
    if (!incomingImage || handledIncomingImage.current === incomingImage.id) return
    handledIncomingImage.current = incomingImage.id
    onIncomingImageConsumed?.(incomingImage.id)
    if (!canCompose || !effectiveWorkspaceRoot) {
      showAttachNotice(t('annotationNeedsWorkspace'))
      incomingImage.settle?.(false)
      return
    }
    void attachImageFiles([incomingImage.file], incomingImage.contextNote).then((attached) => incomingImage.settle?.(attached))
  }, [incomingImage]) // eslint-disable-line react-hooks/exhaustive-deps


  const handleLargePaste = async (text: string): Promise<void> => {
    if (!effectiveWorkspaceRoot) {
      insertTextAtCursor(text)
      return
    }
    if (typeof window.dsGui === 'undefined' || typeof window.dsGui.writePasteTextFile !== 'function') {
      showAttachNotice(t('composerPasteNeedRestart'), 'info')
      insertTextAtCursor(text)
      return
    }
    const target = imageTargetRef.current
    setImageImports((count) => count + 1)
    try {
      const result = await window.dsGui.writePasteTextFile({
        workspaceRoot: effectiveWorkspaceRoot,
        content: text
      })
      if (target !== imageTargetRef.current) return
      if (!result.ok) throw new Error(result.message ?? t('composerPasteFailed'))
      setAttachments((previous) => previous.some((item) => item.path === result.relativePath)
        ? previous
        : [...previous, {
          id: `att-${result.relativePath}`, path: result.relativePath,
          name: result.name, size: result.size
        }])
      showAttachNotice(t('composerPasteSaved', { name: result.name }), 'info')
      focusComposer()
    } catch (error) {
      if (target !== imageTargetRef.current) return
      showAttachNotice(error instanceof Error ? error.message : t('composerPasteFailed'))
      insertTextAtCursor(text)
    } finally {
      setImageImports((count) => count - 1)
    }
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

  const handlePrimaryAction = (fromClick = false): void => {
    if (imageImports > 0) return
    if (voiceActive) return
    if (petSlashQuery != null) {
      const trimmed = input.trim()
      if (/^\/pet\s*$/i.test(trimmed)) {
        if (onApplyPetSlashCommand?.(trimmed)) {
          setInput('')
          focusComposer()
        } else {
          showAttachNotice(t('composerCommandUnknown'))
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
      } else {
        showAttachNotice(t('composerCommandUnknown'))
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
      showAttachNotice(t('composerCommandUnknown'))
      return
    }
    const body = buildOutboundMessage(attachments, input)
    // Prepend the focus target as a leading token so the runtime detects it
    // (chips are UI-only; wire format is unchanged): skill -> `/name`, MCP
    // connector -> `@name`, plugin mount -> `@plugin:name`. Mutually exclusive
    // by construction. Preview picks are also chip-only; JSON context is
    // assembled here so the textarea stays a short user request.
    const focusPrefix = focusSkill
      ? `/${focusSkill}`
      : focusConnector
        ? `@${focusConnector}`
        : focusPlugin
          ? focusPlugin === 'computer-use' ? t('computerUseTaskPrefix') : `@plugin:${focusPlugin}`
          : ''
    // With picks, the focus prefix must stay at the very start of the wire
    // message (runtime detects `/name` / `@name` by line head); nesting it
    // inside the pick JSON's "user request" would break detection.
    const payload = previewPicks.length > 0
      ? [focusPrefix, formatPreviewPickWireMessage(previewPicks, body)]
          .filter(Boolean)
          .join(' ')
          .trim()
      : `${focusPrefix} ${body}`.trim()
    if (!payload.trim()) return
    if (fromClick) lastSendClickAtRef.current = Date.now()
    const sentInput = input
    const sentAttachments = attachments
    const sentThreadId = activeThreadId
    const sentPreviewPicks = previewPicks
    const sentFocusSkill = focusSkill
    const sentFocusConnector = focusConnector
    const sentFocusPlugin = focusPlugin
    setAttachments([])
    setInput('')
    inputRef.current = ''
    setFocusSkill(null)
    setFocusConnector(null)
    setFocusPlugin(null)
    const restoreFailedSend = (): void => {
      const currentId = chatStore.getState().activeThreadId
      const createdId = !sentThreadId && currentId && !threads.some((thread) => thread.id === currentId)
        ? currentId : null
      const targetId = sentThreadId ?? createdId
      if (mountedRef.current && activeThreadIdRef.current === currentId &&
          (sentThreadId === currentId || createdId) && !inputRef.current.trim()) {
        setInput(sentInput)
        setAttachments(sentAttachments)
        setFocusSkill((current) => current ?? sentFocusSkill)
        setFocusConnector((current) => current ?? sentFocusConnector)
        setFocusPlugin((current) => current ?? sentFocusPlugin)
        focusComposer()
      } else if (targetId) {
        paneAttachments.set(targetId, [])
        queueComposerRetryDraft(targetId, payload)
      } else if (mountedRef.current && sentThreadId === null && currentId === null) {
        setInput([sentInput, inputRef.current].filter(Boolean).join('\n'))
        setAttachments((current) => [...sentAttachments, ...current])
      }
    }
    void onSend(payload).then((started) => {
      if (!started) return restoreFailedSend()
      const currentId = chatStore.getState().activeThreadId
      if (mountedRef.current && previewPicksRef.current === sentPreviewPicks &&
          (sentThreadId === currentId || (!sentThreadId && currentId && !threads.some((thread) => thread.id === currentId)))) {
        onClearPreviewPicks?.()
      }
    }).catch(restoreFailedSend)
    focusComposer()
  }

  const handleSendClick = (): void => {
    handlePrimaryAction(true)
  }

  const handleInterruptClick = (): void => {
    if (interruptRequestRef.current || Date.now() - lastSendClickAtRef.current < 400) return
    const request = Symbol()
    interruptRequestRef.current = request
    setInterruptPending(true)
    void Promise.resolve().then(() => onInterrupt()).catch((error) => {
      if (interruptRequestRef.current === request) {
        chatStore.getState().setError(error instanceof Error ? error.message : String(error))
      }
    }).finally(() => {
      if (mountedRef.current && interruptRequestRef.current === request) {
        interruptRequestRef.current = null
        setInterruptPending(false)
      }
    })
  }

  const plusGroups: ComposerPlusGroup[] = [
    {
      id: 'actions', label: t('composerPlusActions'), items: [
        { id: 'files', label: t('composerPlusAddFile'), icon: <Paperclip className="h-[18px] w-[18px]" />, onSelect: () => { void pickAttachments(); focusComposer() } }
      ]
    },
    {
      id: 'modes', label: t('composerPlusMode'), items: ([
          { id: 'goal', label: t('composerModeGoalFull'), description: t('composerModeHintGoal'), icon: Flag },
          { id: 'plan', label: t('composerModePlanFull'), description: t('composerModeHintPlan'), icon: ListTodo },
          { id: 'ask', label: t('composerModeAskFull'), description: t('composerModeHintAsk'), icon: MessageCircleQuestion }
        ] as const).map(({ icon: Icon, ...item }) => ({
          ...item, icon: <Icon className="h-[18px] w-[18px]" />, selected: mode === item.id,
          onSelect: () => { clearAttachNotice(); setMode(mode === item.id ? 'agent' : item.id); focusComposer() }
        }))
    },
    {
      id: 'plugins', label: t('plugins'), loading: pluginsLoading,
      empty: t(runtimeReady ? 'composerPluginsEmpty' : 'composerPluginsNeedRuntime'),
      items: composerPlugins.map(plugin => {
        const visual = pluginVisual(plugin.name)
        const Icon = visual.icon
        return {
          id: `plugin-${plugin.name}`, label: displayPluginName(plugin.name), description: plugin.description,
          keywords: `${plugin.name} ${plugin.name === 'computer-use' ? 'cua' : ''}`,
          icon: <Icon className="h-[18px] w-[18px]" />,
          selected: (focusPlugin ?? activePlugin?.name)?.toLowerCase() === plugin.name.toLowerCase(),
          onSelect: () => handlePickPlugin(plugin.name)
        }
      })
    },
    {
      id: 'skills', label: t('composerPlusSkills'), loading: skillsLoading,
      empty: t(runtimeReady ? 'composerSkillsEmpty' : 'composerSkillsNeedRuntime'),
      items: composerSkills.map(skill => ({
        id: `skill-${skill.name}`, label: skill.name, description: skill.description,
        icon: <Sparkles className="h-[18px] w-[18px]" />, selected: focusSkill === skill.name,
        onSelect: () => handlePickSkill(skill.name)
      }))
    },
    {
      id: 'connectors', label: t('composerPlusConnectors'), loading: connectorsLoading,
      empty: t(runtimeReady ? 'composerConnectorsEmpty' : 'composerConnectorsNeedRuntime'),
      items: composerConnectors.map(connector => ({
        id: `connector-${connector.id}`, label: connector.title, keywords: connector.id,
        description: connector.status === 'connecting' ? t('composerConnectorConnectingHint')
          : connector.status === 'failed' || connector.status === 'disabled'
            ? t('composerConnectorFailedHint', { error: connector.error ? `：${connector.error}` : '' })
            : connector.summary || connector.id,
        icon: <Plug className="h-[18px] w-[18px]" />, disabled: !isComposerConnectorSelectable(connector),
        selected: focusConnector === connector.id, onSelect: () => handlePickConnector(connector.id)
      }))
    }
  ]

  return (
    <div
      className={`pointer-events-auto w-full ${
        useChatStageWidth ? 'ds-chat-stage px-3 sm:px-4' : 'max-w-none px-0'
      } ${compactChrome ? 'pb-0 pt-0' : 'shrink-0 pb-1 pt-0'}`}
      onDragOver={(event) => {
        if (!event.dataTransfer.types.includes(WORKSPACE_PATH_DRAG_MIME) && !event.dataTransfer.types.includes('Files')) return
        event.preventDefault()
        event.dataTransfer.dropEffect = 'copy'
      }}
      onDrop={(event) => {
        const images = Array.from(event.dataTransfer.files).filter((file) => /^image\/(png|jpeg|webp)$/.test(file.type))
        if (images.length) {
          event.preventDefault()
          void attachImageFiles(images)
          return
        }
        const path = workspacePathFromDrag(event.dataTransfer)
        if (!path) return
        event.preventDefault()
        setInput(appendComposerSnippet(inputRef.current, formatComposerPathMention(path)))
        focusComposer()
      }}
    >
      <PendingDecisionPanel key={activeThreadId ?? "empty"} blocks={blocks} />
      <ComposerLiveChangesHeader
        onReview={() => {
          openChangesPanel({
            context: 'last-turn',
            turnId: chatStore.getState().currentTurnId ?? undefined
          })
        }}
      />
      <PublishConflictBanner />
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
            {queuePaused ? (
              <div role="status" className="flex flex-wrap items-center gap-2 text-[12px] text-ds-muted">
                <span>{t('queuedMessagesPausedHint')}</span>
                {onResumeQueuedMessages ? (
                  <button
                    type="button"
                    onClick={onResumeQueuedMessages}
                    className="rounded-full border border-accent/25 bg-accent/10 px-2.5 py-1 text-[12px] font-medium text-accent transition hover:bg-accent/16"
                  >
                    {t('queuedMessagesResume')}
                  </button>
                ) : null}
              </div>
            ) : (
              <div className="text-[12px] text-ds-muted">{t('queuedMessagesHint')}</div>
            )}
          </div>
          <div className="mt-2 flex flex-col gap-2">
            {visibleQueued.map((message, index) => (
              <div
                key={message.id}
                className="ds-queued-message flex min-w-0 max-w-full flex-wrap items-center gap-2 rounded-[12px] border border-ds-border-muted bg-ds-subtle px-3 py-2 text-[13px] text-ds-ink"
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
        {plusMenuOpen && (
          <div ref={plusPanelRef}>
            <ComposerPlusMenu groups={plusGroups} onClose={() => {
              setPlusMenuOpen(false)
              plusMenuRef.current?.querySelector<HTMLButtonElement>('button')?.focus()
            }} />
          </div>
        )}
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
            className={`ds-composer-shell ds-chat-composer flex w-full flex-col transition ${
              compactChrome
                ? 'ds-composer-shell--compact gap-0.5 px-2 py-1'
                : 'ds-composer-empty ds-frosted relative z-10 gap-1.5 px-2 py-1.5 sm:px-2.5'
            } ${focused ? 'ds-chat-composer-focus' : ''}`}
        >
          {attachments.length > 0 ? (
            <div className="flex flex-wrap gap-2 px-1 pt-1">
              {attachments.map((item) => {
                const badge = fileBadge(item.name)
                return (
                  <div
                    key={item.id}
                    // The file name stays the keyboard target; the rest of the card is a larger click area for it.
                    onClick={() => previewWorkspaceFile({ path: item.path, workspaceRoot: effectiveWorkspaceRoot || undefined })}
                    className="flex min-w-[200px] max-w-[260px] cursor-pointer flex-col gap-1.5 overflow-hidden rounded-[14px] border border-ds-border-muted bg-ds-subtle px-2.5 py-2 transition hover:bg-ds-hover"
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] text-[9px] font-semibold tracking-tight ${badge.className}`}
                        aria-hidden
                      >
                        {badge.label}
                      </span>
                      <div className="min-w-0 flex-1">
                        <FileChip
                          path={item.path}
                          label={item.name}
                          skipValidation
                          variant="list"
                          className="max-w-full text-[12px] font-medium"
                        />
                        <div className="mt-0.5 flex items-center gap-1 text-[11px] text-ds-faint">
                          <CheckCircle2
                            className="h-3.5 w-3.5 shrink-0 text-[#10b981]"
                            strokeWidth={2}
                          />
                          <span className="truncate">
                            {t('composerAttachCompleted')}
                            {' · '}
                            {formatBytes(item.size)}
                          </span>
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation()
                          removeAttachment(item.id)
                        }}
                        className="shrink-0 rounded-full p-1 text-ds-faint transition hover:bg-[rgba(239,68,68,0.12)] hover:text-[#dc2626]"
                        aria-label={t('composerAttachmentRemove')}
                      >
                        <Trash2 className="h-3.5 w-3.5" strokeWidth={2} />
                      </button>
                    </div>
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

          {previewPicks.length > 0 ? (
            <div className="flex flex-wrap gap-2 px-1 pt-1">
              {previewPicks.map((pick, index) => {
                const label = formatPreviewPickChipLabel(pick)
                return (
                  <span
                    key={`${pick.filePath}:${pick.selector}:${index}`}
                    title={t('composerPreviewPickFocus', { name: label })}
                    className="ds-no-drag inline-flex max-w-full items-center gap-1 rounded-full border border-[rgba(14,165,233,0.4)] bg-[rgba(14,165,233,0.14)] py-0.5 pl-2.5 pr-1 text-[12px] font-medium text-[#0ea5e9]"
                  >
                    <Wand2 className="h-3 w-3 shrink-0" strokeWidth={2} />
                    <span className="truncate pr-0.5">{label}</span>
                    <button
                      type="button"
                      onClick={() => {
                        onRemovePreviewPick?.(index)
                        focusComposer()
                      }}
                      aria-label={t('composerPreviewPickRemove', { name: label })}
                      title={t('composerPreviewPickRemove', { name: label })}
                      className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[#0ea5e9]/opacity-70 transition hover:bg-[rgba(14,165,233,0.22)] hover:opacity-100"
                    >
                      <X className="h-3 w-3" strokeWidth={2.25} />
                    </button>
                  </span>
                )
              })}
            </div>
          ) : null}

          <textarea
            ref={textareaRef}
            rows={1}
            className={`ds-composer-input ds-no-drag block min-w-0 w-full resize-none break-words bg-transparent text-ds-ink placeholder:text-ds-faint focus:outline-none [overflow-wrap:anywhere] ${
              compactChrome ? 'px-1 py-0.5' : 'px-2 py-1.5'
            } ${canCompose ? '' : 'opacity-80'}`}
            placeholder={
              previewPicks.length > 0 ? t('composerPreviewPickPlaceholder') : placeholder
            }
            value={input}
            disabled={!canCompose || voicePhase === 'transcribing'}
            onChange={(e) => {
              setInput(e.target.value)
              if (voiceActive) resetVoiceSession()
            }}
            onPaste={(event) => {
              const images = Array.from(event.clipboardData.files).filter((file) => /^image\/(png|jpeg|webp)$/.test(file.type))
              if (images.length) {
                event.preventDefault()
                const text = event.clipboardData.getData('text/plain')
                if (text) insertTextAtCursor(text)
                void attachImageFiles(images)
                return
              }
              const text = event.clipboardData?.getData('text/plain') ?? ''
              if (!isLargePaste(text)) return
              event.preventDefault()
              void handleLargePaste(text)
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

          <div
            ref={footerRef}
            data-composer-footer
            data-composer-footer-tier={footerTier}
            className={`flex flex-nowrap items-center ${
              compactChrome ? 'gap-1 px-1' : 'gap-1.5 px-1'
            }`}
          >
            {/* Left chrome: progressive hide via footerPlan (plus last-but-one). */}
            <div className={`relative z-10 flex shrink-0 items-center ${compactChrome ? 'gap-1' : 'gap-1.5'}`}>
            {footerPlan.showPlus ? (
            <div ref={plusMenuRef} className="relative shrink-0">
              <button
                type="button"
                disabled={!canCompose}
                aria-expanded={plusMenuOpen}
                onClick={() => {
                  setActiveCommand(null)
                  clearAttachNotice()
                  if (!plusMenuOpen) {
                    loadComposerSkills()
                    loadComposerConnectors({ force: true })
                    loadComposerPlugins()
                  }
                  setPlusMenuOpen((open) => !open)
                }}
                className={`ds-no-drag inline-flex items-center justify-center rounded-full text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:cursor-not-allowed disabled:opacity-50 ${
                  compactChrome ? 'h-7 w-7' : 'h-9 w-9'
                }`}
                aria-label={t('composerPlusMenu')}
                title={t('composerPlusMenu')}
              >
                <Plus className={compactChrome ? 'h-3.5 w-3.5' : 'h-4 w-4'} strokeWidth={2} />
              </button>

            </div>
            ) : null}

            {footerPlan.showApproval ? (
              <div className="relative z-10 shrink-0">
                <ComposerApprovalPolicySelector
                  disabled={!canCompose}
                  compact={!footerPlan.showApprovalLabel}
                  dense={compactChrome}
                  onOpenChange={(nextOpen) => {
                    if (nextOpen) {
                      setPlusMenuOpen(false)
                    }
                  }}
                />
              </div>
            ) : null}

            {mode !== 'agent' ? (
              <div
                className={`ds-no-drag inline-flex shrink-0 select-none items-center gap-1 px-1 font-semibold text-ds-ink ${
                  compactChrome ? 'h-7 text-[12px]' : 'h-9 gap-1.5 text-[13px]'
                }`}
                title={modeLabel}
              >
                <ModeBadgeIcon
                  className={`${compactChrome ? 'h-3.5 w-3.5' : 'h-4 w-4'} shrink-0`}
                  style={{ color: modeBadge.icon }}
                  strokeWidth={2}
                  aria-hidden
                />
                {footerPlan.showModeLabel ? <span className="truncate">{modeLabel}</span> : null}
              </div>
            ) : null}

            {activePlugin || focusPlugin ? (
              <div
                className={`ds-no-drag group inline-flex max-w-[min(100%,240px)] shrink-0 select-none items-center gap-1 px-1 font-semibold text-[#a855f7] ${
                  compactChrome ? 'h-7 text-[12px]' : 'h-9 gap-1.5 text-[13px]'
                }`}
                title={
                  focusPlugin
                    ? t('composerPluginFocus', { name: displayPluginName(focusPlugin) })
                    : t('composerPluginMounted', {
                        name: displayPluginName(activePlugin!.name),
                        path: activePlugin!.path
                      })
                }
              >
                <Puzzle
                  className={`${compactChrome ? 'h-3.5 w-3.5' : 'h-4 w-4'} shrink-0`}
                  strokeWidth={2}
                  aria-hidden
                />
                {footerPlan.showPluginLabel ? (
                  <span className="truncate">
                    {focusPlugin
                      ? t('composerPluginPendingBadge', { name: displayPluginName(focusPlugin) })
                      : t('composerPluginBadge', { name: displayPluginName(activePlugin!.name) })}
                  </span>
                ) : null}
                <span
                  role="button"
                  tabIndex={0}
                  aria-label={
                    focusPlugin
                      ? t('composerPluginFocus', { name: displayPluginName(focusPlugin) })
                      : t('composerPluginUnmount', { name: displayPluginName(activePlugin!.name) })
                  }
                  onClick={(event) => {
                    event.stopPropagation()
                    if (focusPlugin) {
                      setFocusPlugin(null)
                      focusComposer()
                    } else if (activePlugin) {
                      void sendMessage('@plugin:off')
                    }
                  }}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      event.stopPropagation()
                      if (focusPlugin) {
                        setFocusPlugin(null)
                        focusComposer()
                      } else if (activePlugin) {
                        void sendMessage('@plugin:off')
                      }
                    }
                  }}
                  className="inline-flex items-center rounded-sm p-0.5 opacity-50 transition hover:bg-[rgba(168,85,247,0.16)] hover:opacity-100"
                >
                  <X className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                </span>
              </div>
            ) : null}
            </div>

            {/* Middle: meter + model — progressive hide (meter → effort → model). */}
            <div className="flex min-w-0 flex-1 items-center justify-end gap-1.5">
              {footerPlan.showContextMeter ? (
                <ContextUsageMeter
                  busy={busy}
                  blocks={blocks}
                  model={activeModelId}
                  hasActiveThread={hasActiveThread}
                  threadId={activeThreadId}
                />
              ) : null}
              {footerPlan.showModel ? (
                <div className="min-w-0 max-w-[min(100%,250px)]">
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
                    compact={!footerPlan.showModelLabel}
                    hideEffort
                    dense={compactChrome}
                  />
                </div>
              ) : null}
            </div>

            {/* Voice → plus already gated; send is last to disappear. */}
            <div className={`relative z-20 flex shrink-0 items-center ${compactChrome ? 'gap-1' : 'gap-1.5'}`}>
              {footerPlan.showVoice && isMediaCaptureSupported() ? (
                <button
                  type="button"
                  disabled={voicePhase === 'transcribing' || (voicePhase === 'idle' && !canCompose)}
                  onClick={() =>
                    voicePhase === 'recording' ? handleStopAndTranscribe() : void handleMicClick()
                  }
                  aria-label={voiceButtonTitle}
                  title={voiceButtonTitle}
                  className={`ds-no-drag flex shrink-0 items-center justify-center rounded-full border transition disabled:cursor-not-allowed disabled:opacity-50 ${
                    compactChrome ? 'h-7 w-7' : 'h-9 w-9'
                  } ${
                    voicePhase === 'recording'
                      ? 'border-red-500/45 bg-red-500/15 text-red-600 hover:bg-red-500/25 dark:text-red-300'
                      : 'border-transparent bg-transparent text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
                  }`}
                >
                  {voicePhase === 'recording' ? (
                    <Square className="h-3 w-3 fill-current" strokeWidth={2.4} />
                  ) : (
                    <Mic className={compactChrome ? 'h-3.5 w-3.5' : 'h-4 w-4'} strokeWidth={2} />
                  )}
                </button>
              ) : null}

              {footerPlan.showSend ? (
                busy && !activeHighlightedSlashCommand && voicePhase === 'idle' ? (
                  <button
                    type="button"
                    onClick={handleInterruptClick}
                    disabled={interruptPending}
                    aria-busy={interruptPending}
                    className={`ds-no-drag flex shrink-0 items-center justify-center rounded-full border border-red-500/45 bg-red-500/15 text-red-600 shadow-sm transition hover:bg-red-500/25 hover:text-red-700 dark:text-red-300 dark:hover:text-red-200 ${
                      compactChrome ? 'h-7 w-7' : 'h-9 w-9'
                    }`}
                    aria-label={t(interruptPending ? 'interruptPending' : 'interrupt')}
                    title={t(interruptPending ? 'interruptPending' : 'interrupt')}
                  >
                    {interruptPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : (
                      <Square className="h-3 w-3 fill-current" strokeWidth={2.4} />
                    )}
                  </button>
                ) : (
                  <button
                    type="button"
                    disabled={primaryActionDisabled}
                    onClick={handleSendClick}
                    className={`ds-no-drag flex shrink-0 items-center justify-center rounded-full border border-accent/15 bg-accent text-accent-foreground shadow-[0_10px_24px_rgba(79,124,255,0.28)] transition hover:brightness-110 disabled:cursor-not-allowed disabled:border-transparent disabled:bg-transparent disabled:text-ds-faint disabled:shadow-none ${
                      compactChrome ? 'h-7 w-7' : 'h-9 w-9'
                    }`}
                    aria-label={primaryActionLabel}
                    title={primaryActionLabel}
                  >
                    <Send className={compactChrome ? 'h-3.5 w-3.5' : 'h-4 w-4'} strokeWidth={2.2} />
                  </button>
                )
              ) : null}
            </div>
          </div>
          {compactChrome ? (
            <WorkspaceContextBar
              workspaceRoot={effectiveWorkspaceRoot}
              variant="embedded"
            />
          ) : null}
        </div>
      </div>
      {!compactChrome ? (
        <WorkspaceContextBar workspaceRoot={effectiveWorkspaceRoot} />
      ) : null}
      {!compactChrome && !runtimeReady ? (
        <p className="px-3 pb-1 text-right text-[11.5px] text-amber-700 dark:text-amber-200 sm:px-4">
          {t('composerOfflineHint')}
        </p>
      ) : !compactChrome && !hasActiveThread && !effectiveWorkspaceRoot ? (
        <p className="px-3 pb-1 text-right text-[11.5px] text-ds-faint sm:px-4">{t('composerWorkspaceHint')}</p>
      ) : null}
    </div>
  )
}

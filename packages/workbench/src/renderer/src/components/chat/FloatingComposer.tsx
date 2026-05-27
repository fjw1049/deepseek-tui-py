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
  Clock3,
  FileImage,
  FileText,
  ListTodo,
  MessageCircleQuestion,
  Plus,
  Send,
  ShieldAlert,
  Square,
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
import { ContextUsageMeter } from './ContextUsageMeter'
import { GitBranchPicker } from './GitBranchPicker'

export type ComposerMode = 'plan' | 'agent' | 'ask'

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
  stageCentered?: boolean
  useChatStageWidth?: boolean
}

type SlashCommandId = ComposerMode

type SlashCommand = {
  id: SlashCommandId
  title: string
  description: string
  keywords: string[]
  icon: ReactElement
}

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
  stageCentered = false,
  useChatStageWidth = true
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const activeThreadId = useChatStore((s) => s.activeThreadId)
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
  const activeThreadWorkspace = activeThreadId
    ? threads.find((thread) => thread.id === activeThreadId)?.workspace
    : ''
  const effectiveWorkspaceRoot = normalizeWorkspaceRoot(activeThreadWorkspace || workspaceRoot)

  const pendingApprovalCount = countPendingApprovals(blocks)
  const firstPendingApprovalId = blocks.find(
    (block) => block.kind === 'approval' && block.status === 'pending'
  )?.id

  const canCompose = runtimeReady && (hasActiveThread || !!effectiveWorkspaceRoot)
  const canChangeModel = canCompose && !busy
  const outboundPreview = buildOutboundMessage(attachments, input)
  const canSend = canCompose && outboundPreview.length > 0
  const slashQuery = getSlashQuery(input)
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
        : t('composerModeAgent')

  const modelChipLabel =
    mode === 'agent' ? activeModelLabel : `${modeLabel} · ${activeModelLabel}`

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
        title: t('slashCommandAskTitle'),
        description:
          mode === 'ask'
            ? t('slashCommandAskActiveDescription')
            : t('slashCommandAskDescription'),
        keywords: ['ask', 'question', 'qa', '问答'],
        icon: <MessageCircleQuestion className="h-4 w-4" strokeWidth={1.9} />
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

  const highlightedSlashCommand =
    filteredSlashCommands.length > 0
      ? filteredSlashCommands[Math.min(selectedCommandIndex, filteredSlashCommands.length - 1)]
      : null
  const primaryActionLabel = highlightedSlashCommand
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
  }, [slashQuery])

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

  const applySlashCommand = (commandId: SlashCommandId): void => {
    setMode(commandId)
    setInput('')
    focusComposer()
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
    if (highlightedSlashCommand) {
      applySlashCommand(highlightedSlashCommand.id)
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
        {slashQuery != null ? (
          <div className="ds-card-strong absolute inset-x-2 bottom-full z-30 mb-3 overflow-hidden rounded-[26px] p-2 shadow-[0_26px_70px_rgba(15,23,42,0.16)]">
            <div className="px-3 pb-2 pt-1 text-[12px] font-medium uppercase tracking-[0.14em] text-ds-faint">
              {t('slashCommandMenuTitle')}
            </div>
            {filteredSlashCommands.length > 0 ? (
              <div className="flex flex-col gap-1">
                {filteredSlashCommands.map((command) => {
                  const active = highlightedSlashCommand?.id === command.id
                  return (
                    <button
                      key={command.id}
                      type="button"
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => applySlashCommand(command.id)}
                      className={`flex w-full items-center gap-3 rounded-[20px] px-3 py-3 text-left transition ${
                        active
                          ? 'bg-accent/10 text-ds-ink shadow-[inset_0_0_0_1px_rgba(0,136,255,0.14)]'
                          : 'text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
                      }`}
                    >
                      <span
                        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl ${
                          active ? 'bg-accent/12 text-accent' : 'bg-ds-hover text-ds-muted'
                        }`}
                      >
                        {command.icon}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[15px] font-semibold text-inherit">
                          {command.title}
                        </span>
                        <span className="mt-0.5 block text-[13px] leading-5 text-ds-faint">
                          {command.description}
                        </span>
                      </span>
                      <span className="flex shrink-0 flex-col items-end gap-1">
                        <span className="rounded-full border border-ds-border-muted px-2.5 py-1 text-[11px] font-semibold text-ds-faint">
                          /{command.id}
                        </span>
                        {command.id === mode ? (
                          <span className="rounded-full bg-accent/10 px-2.5 py-1 text-[11px] font-semibold text-accent">
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

              if (!composing && slashQuery != null) {
                if (e.key === 'ArrowDown' && filteredSlashCommands.length > 0) {
                  e.preventDefault()
                  setSelectedCommandIndex((current) => (current + 1) % filteredSlashCommands.length)
                  return
                }
                if (e.key === 'ArrowUp' && filteredSlashCommands.length > 0) {
                  e.preventDefault()
                  setSelectedCommandIndex((current) =>
                    current === 0 ? filteredSlashCommands.length - 1 : current - 1
                  )
                  return
                }
                if (e.key === 'Escape') {
                  e.preventDefault()
                  setInput('')
                  return
                }
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
                <div className="absolute bottom-full left-0 z-40 mb-2 min-w-[220px] overflow-hidden rounded-2xl border border-ds-border bg-ds-card p-1.5 shadow-lg">
                  <div className="px-2 py-1 text-[11px] font-medium uppercase tracking-wide text-ds-faint">
                    {t('composerModeSection')}
                  </div>
                  {(
                    [
                      { id: 'agent' as const, label: t('composerModeAgent'), icon: Bot },
                      { id: 'plan' as const, label: t('composerModePlan'), icon: ListTodo },
                      { id: 'ask' as const, label: t('composerModeAsk'), icon: MessageCircleQuestion }
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

            <div className="relative min-w-0 shrink-0">
              <button
                type="button"
                disabled={!canChangeModel}
                onClick={() => {
                  setPlusMenuOpen(false)
                  clearAttachNotice()
                  setModelMenuOpen((open) => !open)
                }}
                className="ds-no-drag inline-flex max-w-[min(100%,280px)] items-center gap-1.5 rounded-full border border-ds-border bg-ds-card px-3 py-1.5 text-[13px] font-medium text-ds-ink shadow-sm transition hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-50"
                title={t('composerModel')}
              >
                <span className="truncate">{modelChipLabel}</span>
                <ChevronDown className="h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.8} />
              </button>
              {modelMenuOpen ? (
                <div className="absolute bottom-full left-0 z-40 mb-2 min-w-[180px] overflow-hidden rounded-2xl border border-ds-border bg-ds-card p-1.5 shadow-lg">
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

            <div className="min-w-0 flex-1" />

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
      <div className="mt-2 flex min-h-8 items-center justify-between gap-3 px-3 sm:px-4">
        <GitBranchPicker workspaceRoot={effectiveWorkspaceRoot} />
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

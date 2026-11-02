import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { useTranslation } from 'react-i18next'
import { useShallow } from 'zustand/react/shallow'

import type { PetReactionRequest } from '@shared/pet-manifest'
import demoSpritesheet from '../../../asset/pet/demo-spritesheet.webp'
import type { ChatBlock } from '../agent/types'
import { useBrowserAssistanceStore } from '../store/browser-assistance-store'
import { useChatLayoutStore } from '../store/chat-layout-store'
import { useChatStore, useChatStoreApi } from '../store/chat-store'
import {
  firstOtherWaitingThread,
  clearPetAttention,
  subscribePetAttention
} from '../lib/pet/pet-attention'
import {
  bubbleReasonForTurn,
  canPetSpeak,
  mentionsPetName,
  pickPetLineKey,
  rememberPetLine,
  PET_BUBBLE_SHOW_MS,
  PET_WAITING_NUDGE_MS,
  type PetBubbleReason
} from '../lib/pet/pet-bubble'
import { fetchPetManifest, findPetDisplayName, resolvePetSpritesheetSrc } from '../lib/pet/pet-catalog'
import {
  PET_REVEAL_DECISION_EVENT,
  subscribePetEvents,
  type PetActivityEvent
} from '../lib/pet/pet-events'
import {
  readPetAiLines,
  readPetChatter,
  readPetEnabled,
  readPetSlug,
  subscribePetPreferences,
  writePetChatter,
  writePetEnabled
} from '../lib/pet/pet-preferences'
import { parsePetSlashCommand } from '../lib/pet/pet-slash-commands'
import {
  classifyToolWork,
  findPetPendingDecision,
  initialPetMind,
  nextPetWakeAt,
  notePetWork,
  playPetOneShot,
  resetPetWork,
  resolvePetState,
  settlePetMind,
  type PetPendingDecision
} from '../lib/pet/pet-state-machine'
import type { PetStateId } from '../lib/pet/pet-states'

export type PetMascotStatus = 'ready' | 'fallback' | 'hidden'

export type PetBubble = {
  key: string
  text: string
  /** Stays up until its cause is resolved instead of fading out. */
  sticky: boolean
  nudge?: boolean
  action?: { type: 'decision' } | { type: 'thread'; threadId: string }
}

const AI_REASONS: ReadonlySet<PetReactionRequest['reason']> = new Set<PetReactionRequest['reason']>([
  'turn_done', 'turn_recovered', 'tests_failed', 'large_diff', 'petted', 'named'
])
const AI_MIN_GAP_MS = 30_000
const SUMMARY_CHARS = 48

function clip(text: string, max = SUMMARY_CHARS): string {
  const line = text.replace(/\s+/g, ' ').trim()
  return line.length > max ? `${line.slice(0, max - 1)}…` : line
}

function decisionSummary(block: PetPendingDecision): string {
  if (block.kind === 'user_input') return block.questions[0]?.question ?? ''
  if (block.kind === 'elevation') return block.reason
  return block.summary
}

function revealThread(threadId: string): void {
  const layouts = useChatLayoutStore.getState()
  const key = layouts.activeLayoutKey
  const layout = key ? layouts.layouts[key] : undefined
  const pane = layout?.panes.find((candidate) => candidate.threadId === threadId)
  if (key && pane) return layouts.focus(key, pane.id)
  const parked = layout?.parked?.find((candidate) => candidate.threadId === threadId)
  if (key && parked) {
    layouts.restore(key, parked.id)
    return
  }
  void useChatStore.getState().selectThread(threadId)
}

function conversationExcerpt(blocks: ChatBlock[]): string {
  let user = ''
  let answer = ''
  for (let i = blocks.length - 1; i >= 0 && !(user && answer); i -= 1) {
    const block = blocks[i]!
    if (!answer && block.kind === 'assistant') answer = `assistant: ${clip(block.text, 600)}`
    if (!user && block.kind === 'user') user = `user: ${clip(block.text, 200)}`
  }
  return [user, answer].filter(Boolean).join('\n')
}

function isAiReason(reason: PetBubbleReason): reason is PetReactionRequest['reason'] {
  return (AI_REASONS as ReadonlySet<string>).has(reason)
}

export function usePetController() {
  const { t, i18n } = useTranslation('common')
  const storeApi = useChatStoreApi()
  const { busy, activeThreadId, decision, threads } = useChatStore(
    useShallow((state) => ({
      busy: state.busy,
      activeThreadId: state.activeThreadId,
      decision: findPetPendingDecision(state.blocks),
      threads: state.threads
    }))
  )
  const assistance = useBrowserAssistanceStore((state) =>
    state.items.find((item) => item.thread_id === activeThreadId) ?? null)
  const otherWaitingThread = useSyncExternalStore(
    subscribePetAttention,
    () => firstOtherWaitingThread(activeThreadId)
  )
  const waiting = decision != null || assistance != null

  const [enabled, setEnabledState] = useState(() => readPetEnabled())
  const [chatter, setChatterState] = useState(() => readPetChatter())
  const [aiLines, setAiLines] = useState(() => readPetAiLines())
  const [selectedSlug, setSelectedSlug] = useState(() => readPetSlug())
  const [displayName, setDisplayName] = useState<string | null>(null)
  // Null until the chosen sheet is decoded, so the demo pet never flashes first.
  const [spritesheetSrc, setSpritesheetSrc] = useState<string | null>(null)
  const [pageVisible, setPageVisible] = useState(() =>
    typeof document === 'undefined' ? true : !document.hidden
  )
  const [mind, setMind] = useState(initialPetMind)
  const [chatterBubble, setChatterBubble] = useState<PetBubble | null>(null)
  const [hovered, setHovered] = useState(false)
  const [hearts, setHearts] = useState(0)
  const [nudged, setNudged] = useState(false)

  const petName = displayName ?? (selectedSlug.charAt(0).toUpperCase() + selectedSlug.slice(1))
  const activityRef = useRef('')
  const activeToolIdRef = useRef<string | null>(null)
  const failureShownRef = useRef(false)
  const lastSpokeAtRef = useRef(Number.NEGATIVE_INFINITY)
  const lastAiAtRef = useRef(Number.NEGATIVE_INFINITY)
  const recentLinesRef = useRef<string[]>([])
  const speechSeqRef = useRef(0)
  const patFlipRef = useRef(false)
  const live = useRef({ chatter, aiLines, petName, busy, waiting })
  live.current = { chatter, aiLines, petName, busy, waiting }

  useEffect(() => {
    const onVisibilityChange = (): void => setPageVisible(!document.hidden)
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => document.removeEventListener('visibilitychange', onVisibilityChange)
  }, [])

  useEffect(() => subscribePetPreferences(() => {
    setEnabledState(readPetEnabled())
    setChatterState(readPetChatter())
    setAiLines(readPetAiLines())
    setSelectedSlug(readPetSlug())
  }), [])

  // The previous sheet stays on screen until the next one is ready.
  useEffect(() => {
    let cancelled = false
    let revoke: (() => void) | undefined
    void resolvePetSpritesheetSrc(selectedSlug).then((resolved) => {
      if (cancelled || readPetSlug() !== selectedSlug) {
        resolved.revoke()
        return
      }
      revoke = resolved.revoke
      setSpritesheetSrc(resolved.src)
    }).catch(() => {
      if (!cancelled) setSpritesheetSrc(demoSpritesheet)
    })
    return () => {
      cancelled = true
      // Revoke once the replacement has painted, not while it is still shown.
      if (revoke) window.setTimeout(revoke, 1000)
    }
  }, [selectedSlug])

  useEffect(() => {
    let cancelled = false
    setDisplayName(null)
    void fetchPetManifest().then((result) => {
      if (!cancelled && result.ok) setDisplayName(findPetDisplayName(result.manifest, selectedSlug))
    }).catch(() => {})
    return () => { cancelled = true }
  }, [selectedSlug])

  const showChatter = useCallback((text: string) => {
    speechSeqRef.current += 1
    setChatterBubble({ key: `chatter-${speechSeqRef.current}`, text, sticky: false })
  }, [])

  const dismissChatter = useCallback(() => {
    speechSeqRef.current += 1
    setChatterBubble(null)
  }, [])

  useEffect(() => {
    if (!chatterBubble) return
    const timer = window.setTimeout(() => {
      setChatterBubble((current) => (current === chatterBubble ? null : current))
    }, PET_BUBBLE_SHOW_MS)
    return () => window.clearTimeout(timer)
  }, [chatterBubble])

  const say = useCallback((reason: PetBubbleReason, params: Record<string, unknown> = {}) => {
    const now = Date.now()
    const { chatter: allowed, aiLines: useAi, petName: name } = live.current
    if (!allowed || !canPetSpeak(reason, lastSpokeAtRef.current, now)) return
    lastSpokeAtRef.current = now
    const key = pickPetLineKey(reason, recentLinesRef.current)
    const fallback = String(t(key, { name, ...params }))
    recentLinesRef.current = rememberPetLine(recentLinesRef.current, key)
    const react = window.dsGui?.petReact
    if (!useAi || !react || !isAiReason(reason) || now - lastAiAtRef.current < AI_MIN_GAP_MS) {
      showChatter(fallback)
      return
    }
    lastAiAtRef.current = now
    const seq = ++speechSeqRef.current
    void react({
      reason,
      petName: name,
      locale: i18n.language,
      recent: recentLinesRef.current.filter((line) => !line.startsWith('petLine')).slice(-3),
      context: conversationExcerpt(storeApi.getState().blocks)
    }).then((result) => (result.ok ? result.text : fallback), () => fallback).then((text) => {
      // Anything said or sent since the request makes this reply stale.
      if (speechSeqRef.current !== seq) return
      if (text !== fallback) recentLinesRef.current = rememberPetLine(recentLinesRef.current, text)
      showChatter(text)
    })
  }, [i18n.language, showChatter, storeApi, t])
  // Read through a ref so a language change does not resubscribe and reset the pet.
  const sayRef = useRef(say)
  sayRef.current = say

  useEffect(() => {
    const say = (reason: PetBubbleReason, params?: Record<string, unknown>): void =>
      sayRef.current(reason, params)
    setMind(initialPetMind())
    setChatterBubble(null)
    activeToolIdRef.current = null
    failureShownRef.current = false
    activityRef.current = ''

    return subscribePetEvents(activeThreadId, (event: PetActivityEvent) => {
      const now = Date.now()
      if (event.type === 'user_message') {
        activeToolIdRef.current = null
        failureShownRef.current = false
        activityRef.current = ''
        dismissChatter()
        setMind((current) => playPetOneShot(resetPetWork(current, now), 'jumping', 'decorative', now))
        if (event.text && mentionsPetName(event.text, live.current.petName)) say('named')
      } else if (event.type === 'agent_reasoning') {
        if (activeToolIdRef.current == null) setMind((current) => notePetWork(current, 'review', now))
      } else if (event.type === 'tool_started') {
        activeToolIdRef.current = event.itemId
        activityRef.current = event.summary
        setMind((current) => notePetWork(current, classifyToolWork(event), now))
      } else if (event.type === 'tool_completed') {
        if (activeToolIdRef.current === event.itemId) activeToolIdRef.current = null
      } else if (event.type === 'subagent_started') {
        activityRef.current = event.agentType
        setMind((current) => notePetWork(current, 'running', now))
      } else if (event.type === 'turn_error') {
        if (failureShownRef.current) return
        failureShownRef.current = true
        setMind((current) => playPetOneShot(current, 'failed', 'critical', now))
        say('stream_error')
      } else if (event.type === 'turn_complete') {
        activeToolIdRef.current = null
        const { digest } = event
        if (digest.outcome === 'cancelled') {
          setMind((current) => ({ ...current, oneShot: null }))
          return
        }
        if (digest.outcome === 'failed') {
          if (failureShownRef.current) return
          failureShownRef.current = true
          setMind((current) => playPetOneShot(current, 'failed', 'critical', now))
        } else {
          setMind((current) => playPetOneShot(current, 'waving', 'decorative', now))
        }
        const reason = bubbleReasonForTurn(digest)
        if (reason) say(reason, { count: digest.toolErrors, lines: digest.diffLines })
      }
    })
  }, [activeThreadId, dismissChatter])

  useEffect(() => {
    const wakeAt = nextPetWakeAt(mind)
    if (wakeAt == null) return
    const timer = window.setTimeout(
      () => setMind((current) => settlePetMind(current, Date.now())),
      Math.max(0, wakeAt - Date.now())
    )
    return () => window.clearTimeout(timer)
  }, [mind])

  // A thread looked at with nothing pending no longer needs a reminder elsewhere.
  useEffect(() => {
    if (activeThreadId && !waiting) clearPetAttention(activeThreadId)
  }, [activeThreadId, waiting])

  const decisionKey = decision?.id ?? (assistance ? `assistance-${assistance.id}` : null)
  useEffect(() => {
    setNudged(false)
    if (!decisionKey) return
    const timer = window.setTimeout(() => setNudged(true), PET_WAITING_NUDGE_MS)
    return () => window.clearTimeout(timer)
  }, [decisionKey])

  const stateId: PetStateId = resolvePetState({ mind, busy, waiting })

  const otherTitle = otherWaitingThread
    ? threads.find((thread) => thread.id === otherWaitingThread)?.title ?? ''
    : ''
  const stickyBubble = useMemo<PetBubble | null>(() => {
    if (decision || assistance) {
      const what = clip(decision ? decisionSummary(decision) : assistance!.reason)
      const lineKey = decision?.kind === 'user_input'
        ? 'petNeedsInput'
        : assistance && !decision ? 'petNeedsBrowser' : 'petNeedsApproval'
      return {
        key: `${decisionKey}-${nudged ? 'nudge' : 'first'}`,
        text: String(t(nudged ? `${lineKey}Again` : lineKey, { what })),
        sticky: true,
        nudge: nudged,
        action: { type: 'decision' }
      }
    }
    if (otherWaitingThread) {
      return {
        key: `other-${otherWaitingThread}`,
        text: String(t('petOtherTaskWaiting', { title: clip(otherTitle, 24) || t('petOtherTaskUntitled') })),
        sticky: true,
        action: { type: 'thread', threadId: otherWaitingThread }
      }
    }
    return null
  }, [assistance, decision, decisionKey, nudged, otherTitle, otherWaitingThread, t])

  const hoverBubble: PetBubble | null = hovered && !stickyBubble && !chatterBubble
    ? {
        key: 'hover',
        sticky: true,
        text: String(busy
          ? t('petStatusWorking', { name: petName, what: clip(activityRef.current) || t('petStatusThinking') })
          : t('petStatusIdle', { name: petName }))
      }
    : null
  const bubble = stickyBubble ?? chatterBubble ?? hoverBubble

  const revealDecision = useCallback(() => {
    window.dispatchEvent(new CustomEvent(PET_REVEAL_DECISION_EVENT, { detail: { threadId: activeThreadId } }))
  }, [activeThreadId])

  const pat = useCallback(() => {
    const now = Date.now()
    patFlipRef.current = !patFlipRef.current
    setHearts((count) => count + 1)
    setMind((current) => playPetOneShot(current, patFlipRef.current ? 'jumping' : 'waving', 'decorative', now))
    say('petted')
  }, [say])

  const onBubbleAction = useCallback((target: PetBubble) => {
    if (target.action?.type === 'decision') revealDecision()
    else if (target.action?.type === 'thread') revealThread(target.action.threadId)
    else if (!target.sticky) dismissChatter()
  }, [dismissChatter, revealDecision])

  /** A click asks for attention first: pending decisions win over petting. */
  const activate = useCallback(() => {
    if (stickyBubble?.action) onBubbleAction(stickyBubble)
    else pat()
  }, [onBubbleAction, pat, stickyBubble])

  const setEnabled = useCallback((next: boolean) => {
    setEnabledState(next)
    writePetEnabled(next)
  }, [])

  const handlePetSlash = useCallback((input: string): boolean => {
    const action = parsePetSlashCommand(input)
    if (!action || action.type === 'unknown') return false
    const wake = (): void => { if (!enabled) setEnabled(true) }
    if (action.type === 'burst') {
      wake()
      setMind((current) => playPetOneShot(current, action.stateId, 'decorative', Date.now()))
    } else if (action.type === 'pat') {
      wake()
      pat()
    } else if (action.type === 'set_enabled') {
      setEnabled(action.enabled)
    } else if (action.type === 'set_chatter') {
      setChatterState(action.enabled)
      writePetChatter(action.enabled)
      if (!action.enabled) dismissChatter()
    } else {
      setEnabled(!enabled)
    }
    return true
  }, [dismissChatter, enabled, pat, setEnabled])

  const status: PetMascotStatus = !enabled || spritesheetSrc == null
    ? 'hidden'
    : spritesheetSrc === demoSpritesheet ? 'fallback' : 'ready'

  return {
    stateId,
    playKey: mind.oneShot ? mind.playKey : 0,
    spritesheetSrc: spritesheetSrc ?? demoSpritesheet,
    status,
    enabled,
    selectedSlug,
    petName,
    bubble,
    hearts,
    canStroll: pageVisible && stateId === 'idle' && !bubble,
    motionPaused: !pageVisible,
    setEnabled,
    setHovered,
    activate,
    onBubbleAction,
    handlePetSlash
  }
}

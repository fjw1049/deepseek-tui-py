import {
  useLayoutEffect,
  useRef,
  useState,
  type MutableRefObject,
  type RefObject
} from 'react'
import {
  TAIL_ANCHOR_TOP_INSET_PX,
  computeTailAnchorScrollTop,
  computeTailAnchorSpacerPx,
  shouldReleaseTailAnchor
} from './message-timeline-logic'

function readUiScale(): number {
  return (
    parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--ds-ui-scale')) || 1
  )
}

function contentOffset(
  container: HTMLElement,
  node: HTMLElement,
  uiScale: number
): { top: number; height: number } {
  const containerRect = container.getBoundingClientRect()
  const rect = node.getBoundingClientRect()
  return {
    top: (rect.top - containerRect.top) / uiScale + container.scrollTop,
    height: rect.height / uiScale
  }
}

/**
 * After send, pin the user bubble to the top of the transcript and grow a
 * spacer beneath the live turn. When the answer fills the viewport, hand off
 * to stick-to-bottom. The spacer stays after the turn settles so collapsing
 * it cannot yank the transcript.
 */
export function useTailAnchorScroll(input: {
  containerRef: RefObject<HTMLDivElement | null>
  sentUserId: string | null
  threadId: string | null
  stickToBottomRef: MutableRefObject<boolean>
  userScrolledAtRef: MutableRefObject<number>
}): { spacerPx: number; holdRef: MutableRefObject<boolean> } {
  const { containerRef, sentUserId, threadId, stickToBottomRef, userScrolledAtRef } = input
  const [spacerPx, setSpacerPx] = useState(0)
  const holdRef = useRef(false)
  const releasedByUserRef = useRef(false)
  const anchorUserIdRef = useRef<string | null>(null)
  const lastSentUserIdRef = useRef<string | null>(null)

  useLayoutEffect(() => {
    anchorUserIdRef.current = null
    lastSentUserIdRef.current = null
    holdRef.current = false
    releasedByUserRef.current = false
    setSpacerPx(0)
  }, [threadId])

  useLayoutEffect(() => {
    if (!sentUserId || sentUserId === lastSentUserIdRef.current) return
    lastSentUserIdRef.current = sentUserId
    anchorUserIdRef.current = sentUserId
    holdRef.current = true
    releasedByUserRef.current = false
    stickToBottomRef.current = false
  }, [sentUserId, stickToBottomRef])

  useLayoutEffect(() => {
    const container = containerRef.current
    const userId = anchorUserIdRef.current
    if (!container || !userId) return

    const measure = (): void => {
      const user = document.getElementById(`block-${userId}`)
      const turn = user?.closest('.ds-message-turn')
      if (!(user instanceof HTMLElement) || !(turn instanceof HTMLElement)) return

      const uiScale = readUiScale()
      const userBox = contentOffset(container, user, uiScale)
      const turnBox = contentOffset(container, turn, uiScale)
      const contentAfterUser = Math.max(0, turnBox.top + turnBox.height - (userBox.top + userBox.height))
      const nextSpacer = computeTailAnchorSpacerPx({
        viewportHeight: container.clientHeight,
        userHeight: userBox.height,
        contentAfterUser
      })

      if (Math.abs(nextSpacer - spacerPx) > 1) {
        setSpacerPx(nextSpacer)
      }

      const userScrolled =
        releasedByUserRef.current || performance.now() - userScrolledAtRef.current < 350
      if (userScrolled) {
        releasedByUserRef.current = true
        holdRef.current = false
        return
      }

      if (shouldReleaseTailAnchor({ spacerPx: nextSpacer, userScrolled: false })) {
        holdRef.current = false
        stickToBottomRef.current = true
        container.scrollTop = container.scrollHeight
        return
      }

      if (!holdRef.current) return
      container.scrollTop = computeTailAnchorScrollTop({ userOffsetTop: userBox.top })
    }

    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(container)
    const stack = container.querySelector('.ds-timeline-stack')
    if (stack) observer.observe(stack)
    return () => observer.disconnect()
  }, [containerRef, sentUserId, spacerPx, stickToBottomRef, threadId, userScrolledAtRef])

  return { spacerPx, holdRef }
}

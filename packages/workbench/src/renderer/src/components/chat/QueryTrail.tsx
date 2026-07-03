// FILE: QueryTrail.tsx
// Purpose: Left-gutter query rail with macOS-Dock-style magnification. The tick
//   nearest the pointer grows longest (Gaussian falloff on neighbours) and a side
//   tooltip shows that focused query + the start of its reply. The hot path writes
//   tick width/opacity straight to the DOM inside one coalesced rAF — no React
//   state per pointer move — so it stays smooth and never re-renders the timeline.
//   Ported faithfully from synara's MessageTrail.tsx.
// Depends on: pure magnification math in queryTrail.logic.ts.

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type FocusEvent as ReactFocusEvent,
  type WheelEvent as ReactWheelEvent
} from 'react'
import { useChatStore } from '../../store/chat-store'
import {
  clampNumber,
  clampTooltipTop,
  computeFocusedIndex,
  computeGaussianWeights,
  computeRestStyles,
  computeSigma,
  computeTickStyles,
  computeTrailGeometry,
  type ActiveTrailStore,
  type QueryTrailItem,
  type TickStyle,
  type TrailGeometry
} from './queryTrail.logic'

type Props = {
  items: QueryTrailItem[]
  /** External store carrying the active/visible trail highlights (scroll-spy writes here). */
  activeStore: ActiveTrailStore
}

// Fixed rail box. Ticks grow rightward inside it (left-aligned, like the Dock).
// Geometry mirrors synara's MessageTrail so the rail hugs the content card's
// left edge with ink-coloured 2px dashes.
const RAIL_WIDTH_PX = 56
const RAIL_MAX_HEIGHT_RATIO = 0.8
const MIN_PANE_WIDTH_PX = 864
const TICK_LEFT_PAD_PX = 14
const TICK_HEIGHT_PX = 2
const TICK_BASE_W = 6
const TICK_MAX_W = 30
const TICK_SPACING_PX = 10
const TICK_REST_OPACITY = 0.2
const TICK_VISIBLE_OPACITY = 0.52
const TICK_ANCHOR_OPACITY = 0.9
const TICK_FOCUS_OPACITY = 1
const TOOLTIP_ESTIMATED_H_PX = 56
const TOOLTIP_OFFSET_X_PX = 8

function readUiScale(): number {
  return (
    parseFloat(
      getComputedStyle(document.documentElement).getPropertyValue('--ds-ui-scale')
    ) || 1
  )
}

export function QueryTrail({ items, activeStore }: Props): React.ReactElement | null {
  const scrollToBlock = useChatStore((s) => s.scrollToBlock)
  // Subscribe to scroll-spy highlights via an external store so the heavy
  // timeline never re-renders when the active tick changes on scroll.
  const snapshot = useSyncExternalStore(activeStore.subscribe, activeStore.get)
  const currentId = snapshot.currentId
  const visibleIds = snapshot.visibleIds

  const rootRef = useRef<HTMLElement | null>(null)
  const viewportRef = useRef<HTMLDivElement | null>(null)
  const tooltipRef = useRef<HTMLDivElement | null>(null)
  const tooltipQueryRef = useRef<HTMLDivElement | null>(null)
  const tooltipReplyRef = useRef<HTMLDivElement | null>(null)
  const tickRefs = useRef<(HTMLButtonElement | null)[]>([])
  const tooltipId = useId()

  const [rovingIndex, setRovingIndex] = useState(0)
  // Synara hides the trail on narrow panes: it needs a real left gutter to
  // live in without crowding the dialogue column.
  const [paneWide, setPaneWide] = useState(true)

  useEffect(() => {
    const nav = rootRef.current
    if (!nav) return
    // Measure the containing block (the content card's main row) — the rail is
    // absolutely positioned against it, so that width is the real "pane" the
    // rail lives in (synara gates on the transcript pane, not the text column).
    const el = (nav.offsetParent as HTMLElement | null) ?? nav.parentElement
    if (!el) return
    const update = (): void => setPaneWide(el.clientWidth >= MIN_PANE_WIDTH_PX)
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const anchorIndex = useMemo(
    () => items.findIndex((item) => item.id === currentId),
    [items, currentId]
  )
  const visibleIndexes = useMemo(() => {
    if (visibleIds.length === 0) return []
    const set = new Set(visibleIds)
    const out: number[] = []
    items.forEach((item, index) => {
      if (set.has(item.id)) out.push(index)
    })
    return out
  }, [items, visibleIds])
  const visibleIndexSet = useMemo(() => new Set(visibleIndexes), [visibleIndexes])

  const visible = items.length > 1 && paneWide

  const geometry = useMemo(
    () => computeTrailGeometry({ count: items.length, spacingPx: TICK_SPACING_PX }),
    [items.length]
  )

  // --- Hot-path refs (read inside rAF; never trigger renders) ---------------
  const rafIdRef = useRef<number | null>(null)
  const latestPointerContentOffsetRef = useRef<number | null>(null)
  const focusOverrideIndexRef = useRef<number | null>(null)
  const geometryRef = useRef<TrailGeometry | null>(geometry)
  geometryRef.current = geometry
  const viewportTopRef = useRef(0)
  const uiScaleRef = useRef(1)
  const tooltipIndexRef = useRef(-1)
  const reducedMotionRef = useRef(false)
  const itemsRef = useRef(items)
  itemsRef.current = items
  const anchorIndexRef = useRef(anchorIndex)
  anchorIndexRef.current = anchorIndex
  const visibleIndexesRef = useRef(visibleIndexes)
  visibleIndexesRef.current = visibleIndexes
  const visibleRef = useRef(visible)
  visibleRef.current = visible

  if (tickRefs.current.length !== items.length) {
    tickRefs.current = Array.from<HTMLButtonElement | null>({ length: items.length }).fill(null)
  }

  // --- Imperative writers ----------------------------------------------------
  const writeStyles = useCallback((styles: readonly TickStyle[]) => {
    const refs = tickRefs.current
    for (let i = 0; i < styles.length; i += 1) {
      const el = refs[i]
      if (!el) continue
      el.style.width = `${styles[i]!.width}px`
      el.style.opacity = `${styles[i]!.opacity}`
    }
  }, [])

  const hideTooltip = useCallback(() => {
    tooltipIndexRef.current = -1
    const tip = tooltipRef.current
    if (tip) tip.style.visibility = 'hidden'
  }, [])

  const showTooltip = useCallback((index: number, geometryValue: TrailGeometry) => {
    const tip = tooltipRef.current
    const item = itemsRef.current[index]
    if (!tip || !item) return
    if (tooltipIndexRef.current !== index) {
      tooltipIndexRef.current = index
      const queryEl = tooltipQueryRef.current
      const replyEl = tooltipReplyRef.current
      if (queryEl) queryEl.textContent = item.preview
      if (replyEl) {
        replyEl.textContent = item.responsePreview
        replyEl.style.display = item.responsePreview ? '' : 'none'
      }
    }
    // Ticks live in scrolling content space; the tooltip is a non-scrolling sibling,
    // so map the tick centre into the viewport (minus scrollTop) and offset by where
    // the centred viewport sits inside the full-height rail (viewport.offsetTop).
    const viewport = viewportRef.current
    const viewportHeight = viewport?.clientHeight ?? 0
    const tooltipHeight = tip.offsetHeight || TOOLTIP_ESTIMATED_H_PX
    const centerY = geometryValue.centerYs[index] ?? viewportHeight / 2
    const visibleY = centerY - (viewport?.scrollTop ?? 0)
    const offsetTop = viewport?.offsetTop ?? 0
    tip.style.top = `${offsetTop + clampTooltipTop(visibleY, tooltipHeight, viewportHeight)}px`
    tip.style.visibility = 'visible'
  }, [])

  const applyHighlightFloors = useCallback((styles: TickStyle[]) => {
    for (const index of visibleIndexesRef.current) {
      const style = styles[index]
      if (style) style.opacity = Math.max(style.opacity, TICK_VISIBLE_OPACITY)
    }
    const anchor = anchorIndexRef.current
    const anchorStyle = anchor >= 0 ? styles[anchor] : undefined
    if (anchorStyle) anchorStyle.opacity = Math.max(anchorStyle.opacity, TICK_ANCHOR_OPACITY)
  }, [])

  const applyRest = useCallback(() => {
    const styles = computeRestStyles(
      itemsRef.current.length,
      anchorIndexRef.current,
      TICK_BASE_W,
      TICK_REST_OPACITY,
      TICK_ANCHOR_OPACITY
    )
    applyHighlightFloors(styles)
    writeStyles(styles)
    hideTooltip()
  }, [applyHighlightFloors, hideTooltip, writeStyles])

  const layoutTicks = useCallback(() => {
    const geometryValue = geometryRef.current
    if (!geometryValue) return
    const refs = tickRefs.current
    for (let i = 0; i < refs.length; i += 1) {
      const el = refs[i]
      if (!el) continue
      const centerY = geometryValue.centerYs[i] ?? 0
      el.style.top = `${centerY - TICK_HEIGHT_PX / 2}px`
    }
    if (latestPointerContentOffsetRef.current === null && focusOverrideIndexRef.current === null) {
      applyRest()
    }
  }, [applyRest])

  // --- The magnification frame (single coalesced rAF) ------------------------
  const renderFrame = useCallback(() => {
    rafIdRef.current = null
    const geometryValue = geometryRef.current
    if (!geometryValue || !visibleRef.current) return
    const count = itemsRef.current.length
    if (count === 0) return

    // The stored pointer offset is already in content space (viewport-relative,
    // unscaled); add the live scrollTop to follow rail scrolling.
    let activeY: number | null = null
    const pointerOffset = latestPointerContentOffsetRef.current
    if (pointerOffset !== null) {
      activeY = pointerOffset + (viewportRef.current?.scrollTop ?? 0)
    } else if (focusOverrideIndexRef.current !== null) {
      activeY = geometryValue.centerYs[focusOverrideIndexRef.current] ?? null
    }
    if (activeY === null) {
      applyRest()
      return
    }
    const anchor = anchorIndexRef.current
    const focusedIndex = computeFocusedIndex(activeY, geometryValue)

    let styles: TickStyle[]
    if (geometryValue.spacing === 0 || reducedMotionRef.current) {
      styles = computeRestStyles(count, anchor, TICK_BASE_W, TICK_REST_OPACITY, TICK_ANCHOR_OPACITY)
      const focusedStyle = styles[focusedIndex]
      if (focusedStyle) focusedStyle.width = TICK_MAX_W
    } else {
      const sigma = computeSigma(geometryValue.spacing)
      const weights = computeGaussianWeights(geometryValue.centerYs, activeY, sigma)
      styles = computeTickStyles(
        weights,
        anchor,
        TICK_BASE_W,
        TICK_MAX_W,
        TICK_REST_OPACITY,
        TICK_ANCHOR_OPACITY
      )
    }
    applyHighlightFloors(styles)
    const focusedStyle = styles[focusedIndex]
    if (focusedStyle) focusedStyle.opacity = TICK_FOCUS_OPACITY
    writeStyles(styles)
    showTooltip(focusedIndex, geometryValue)
  }, [applyHighlightFloors, applyRest, showTooltip, writeStyles])

  const scheduleFrame = useCallback(() => {
    if (rafIdRef.current === null) rafIdRef.current = requestAnimationFrame(renderFrame)
  }, [renderFrame])

  const cancelFrame = useCallback(() => {
    if (rafIdRef.current !== null) {
      cancelAnimationFrame(rafIdRef.current)
      rafIdRef.current = null
    }
  }, [])

  // Reposition ticks whenever the layout changes (count → new centres).
  useEffect(() => {
    layoutTicks()
  }, [geometry, layoutTicks])

  // Refresh idle highlights when anchor / visible-set changes.
  useEffect(() => {
    if (latestPointerContentOffsetRef.current === null && focusOverrideIndexRef.current === null) {
      applyRest()
    }
  }, [anchorIndex, applyRest, visibleIndexes])

  useEffect(() => {
    reducedMotionRef.current =
      typeof window !== 'undefined' && typeof window.matchMedia === 'function'
        ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
        : false
  }, [])

  useEffect(() => {
    if (!visible) {
      cancelFrame()
      latestPointerContentOffsetRef.current = null
      focusOverrideIndexRef.current = null
      hideTooltip()
    }
  }, [visible, cancelFrame, hideTooltip])

  useEffect(() => cancelFrame, [cancelFrame])

  // --- Pointer handlers (mouse / pen only; touch must not hijack scroll) -----
  const captureViewportFrame = useCallback(() => {
    const rect = viewportRef.current?.getBoundingClientRect()
    if (rect) viewportTopRef.current = rect.top
    uiScaleRef.current = readUiScale()
  }, [])

  // clientY is post-zoom (scaled) viewport coords; the viewport rect is too. Their
  // difference is a scaled offset — divide by the UI scale to land in the unscaled
  // content-space the tick geometry (scrollTop, centerYs) is measured in.
  const toContentOffset = useCallback((clientY: number): number => {
    const scale = uiScaleRef.current || 1
    return (clientY - viewportTopRef.current) / scale
  }, [])

  const handlePointerMove = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (event.pointerType === 'touch' || !visibleRef.current) return
      latestPointerContentOffsetRef.current = toContentOffset(event.clientY)
      scheduleFrame()
    },
    [scheduleFrame, toContentOffset]
  )

  const handlePointerEnter = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (event.pointerType === 'touch' || !visibleRef.current) return
      captureViewportFrame()
      latestPointerContentOffsetRef.current = toContentOffset(event.clientY)
      scheduleFrame()
    },
    [captureViewportFrame, scheduleFrame, toContentOffset]
  )

  const handlePointerLeave = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (event.pointerType === 'touch') return
      latestPointerContentOffsetRef.current = null
      cancelFrame()
      if (focusOverrideIndexRef.current !== null) scheduleFrame()
      else applyRest()
    },
    [applyRest, cancelFrame, scheduleFrame]
  )

  const handleScroll = useCallback(() => {
    if (latestPointerContentOffsetRef.current !== null || focusOverrideIndexRef.current !== null) {
      scheduleFrame()
    }
  }, [scheduleFrame])

  // Full-height hit area: clicking anywhere on the rail (the whole nav column,
  // not just the centred tick band) jumps to the nearest tick — like a scrollbar.
  // The tick band is centred in the nav via `justify-center`, so map the nav-relative
  // click Y into the band's content space (accounting for the centred offset and any
  // inner viewport scroll) before resolving the nearest tick.
  const handleNavClick = useCallback(
    (event: ReactMouseEvent<HTMLElement>) => {
      const geometryValue = geometryRef.current
      const nav = rootRef.current
      const viewport = viewportRef.current
      if (!geometryValue || !nav) return
      const scale = readUiScale()
      const navRect = nav.getBoundingClientRect()
      const navHeight = navRect.height / scale
      const viewportHeight = viewport?.clientHeight ?? geometryValue.contentHeight
      const bandTop = (navHeight - viewportHeight) / 2
      const yInNav = (event.clientY - navRect.top) / scale
      const contentY = yInNav - bandTop + (viewport?.scrollTop ?? 0)
      const index = computeFocusedIndex(contentY, geometryValue)
      const item = itemsRef.current[index]
      if (item) scrollToBlock(item.id)
    },
    [scrollToBlock]
  )

  // The rail overlays the card's left gutter, so without help a wheel gesture
  // over it hits the rail's own (usually non-scrollable) viewport and the chat
  // never moves — the strip feels like a dead zone. Forward the wheel to the
  // chat scroller unless the rail's viewport genuinely overflows and the
  // gesture happened inside it (then native rail scrolling should win).
  const handleWheel = useCallback((event: ReactWheelEvent<HTMLElement>) => {
    const viewport = viewportRef.current
    if (
      viewport &&
      viewport.scrollHeight > viewport.clientHeight + 1 &&
      event.target instanceof Node &&
      viewport.contains(event.target)
    ) {
      return
    }
    const scroller = rootRef.current
      ?.closest('.ds-chat-main-row')
      ?.querySelector<HTMLElement>('.ds-scroll-surface')
    if (!scroller) return
    const lineFactor = event.deltaMode === 1 ? 16 : 1
    scroller.scrollTop += (event.deltaY * lineFactor) / readUiScale()
  }, [])

  // --- Keyboard: one tab stop (roving), arrows move, Enter jumps -------------
  const focusTick = useCallback((index: number) => {
    setRovingIndex(index)
    tickRefs.current[index]?.focus()
  }, [])

  const handleKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLElement>) => {
      const count = itemsRef.current.length
      if (count === 0) return
      const current = clampNumber(rovingIndex, 0, count - 1)
      switch (event.key) {
        case 'ArrowDown':
          event.preventDefault()
          focusTick(Math.min(count - 1, current + 1))
          break
        case 'ArrowUp':
          event.preventDefault()
          focusTick(Math.max(0, current - 1))
          break
        case 'Home':
          event.preventDefault()
          focusTick(0)
          break
        case 'End':
          event.preventDefault()
          focusTick(count - 1)
          break
        case 'Enter':
        case ' ': {
          event.preventDefault()
          const item = itemsRef.current[current]
          if (item) scrollToBlock(item.id)
          break
        }
        case 'Escape':
          tickRefs.current[current]?.blur()
          break
        default:
          break
      }
    },
    [focusTick, rovingIndex, scrollToBlock]
  )

  const handleTickFocus = useCallback(
    (index: number) => {
      focusOverrideIndexRef.current = index
      const geometryValue = geometryRef.current
      if (geometryValue) showTooltip(index, geometryValue)
      scheduleFrame()
    },
    [scheduleFrame, showTooltip]
  )

  const handleRailBlur = useCallback(
    (event: ReactFocusEvent<HTMLElement>) => {
      const root = rootRef.current
      if (root && event.relatedTarget instanceof Node && root.contains(event.relatedTarget)) {
        return
      }
      focusOverrideIndexRef.current = null
      if (latestPointerContentOffsetRef.current === null) applyRest()
    },
    [applyRest]
  )

  const tabStop = clampNumber(rovingIndex, 0, Math.max(0, items.length - 1))

  if (!geometry || items.length === 0) return null

  return (
    <nav
      ref={rootRef}
      aria-label="Query navigation"
      aria-hidden={!visible}
      onKeyDown={handleKeyDown}
      onBlur={handleRailBlur}
      onClick={handleNavClick}
      onWheel={handleWheel}
      // ds-no-drag is load-bearing: the rail hugs the card's left edge inside the
      // ds-drag titlebar section, and Electron eats pointer events over drag
      // regions — without it the magnification/wheel stutter with a real mouse.
      className={`ds-no-drag absolute inset-y-0 left-0 z-20 hidden flex-col justify-center transition-opacity duration-200 sm:flex ${
        visible ? 'opacity-100' : 'pointer-events-none opacity-0'
      }`}
      style={{ width: RAIL_WIDTH_PX }}
    >
      {/* Capped, centered, scrollable viewport. Pointer handlers live here (like the
          synara source) — the ticks read as one close centred stack. Click is on the
          nav wrapper so the whole column is the hit area, not just this band. */}
      <div
        ref={viewportRef}
        onPointerEnter={handlePointerEnter}
        onPointerMove={handlePointerMove}
        onPointerLeave={handlePointerLeave}
        onScroll={handleScroll}
        className={`relative w-full overflow-y-auto overscroll-contain [contain:layout] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden ${
          visible ? 'pointer-events-auto' : 'pointer-events-none'
        }`}
        style={{ maxHeight: `${RAIL_MAX_HEIGHT_RATIO * 100}%` }}
      >
        <div className="relative w-full" style={{ height: geometry.contentHeight }}>
          {items.map((item, index) => (
            <button
              key={item.id}
              ref={(el) => {
                tickRefs.current[index] = el
              }}
              type="button"
              tabIndex={visible && index === tabStop ? 0 : -1}
              aria-label={`Query ${item.ordinal}: ${item.preview.slice(0, 60)}`}
              aria-describedby={tooltipId}
              aria-current={index === anchorIndex ? 'location' : undefined}
              onFocus={() => handleTickFocus(index)}
              className="absolute rounded-full outline-none transition-[width,opacity] duration-[90ms] ease-out focus-visible:ring-2 focus-visible:ring-[color:var(--ds-accent)] motion-reduce:transition-none"
              style={{
                left: TICK_LEFT_PAD_PX,
                height: TICK_HEIGHT_PX,
                width: TICK_BASE_W,
                opacity:
                  index === anchorIndex
                    ? TICK_ANCHOR_OPACITY
                    : visibleIndexSet.has(index)
                      ? TICK_VISIBLE_OPACITY
                      : TICK_REST_OPACITY,
                backgroundColor: 'var(--ds-text)',
                willChange: 'width, opacity'
              }}
            />
          ))}
        </div>
      </div>
      <div
        ref={tooltipRef}
        role="tooltip"
        id={tooltipId}
        className="pointer-events-none invisible absolute z-30 w-64 -translate-y-1/2 rounded-xl border border-[color:var(--ds-border)] bg-[color:var(--ds-card-soft)] p-2.5 shadow-lg backdrop-blur-xl"
        style={{ left: RAIL_WIDTH_PX + TOOLTIP_OFFSET_X_PX, top: 0 }}
      >
        <div
          ref={tooltipQueryRef}
          className="line-clamp-2 text-xs font-medium leading-snug text-ds-ink"
        />
        <div
          ref={tooltipReplyRef}
          className="mt-1 line-clamp-3 text-xs leading-snug text-ds-muted"
        />
      </div>
    </nav>
  )
}

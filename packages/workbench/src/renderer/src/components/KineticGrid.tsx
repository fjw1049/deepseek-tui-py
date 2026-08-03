import { useEffect, useRef, type CSSProperties } from 'react'

/**
 * KineticGrid — interactive mesh background that reacts to cursor movement.
 *
 * Faithful port of OriginKit "Kinetic Grid" physics/draw constants. Colors
 * follow the app theme by default (light board + dark dots / dark board +
 * white dots) so the cold-start splash matches the shell; pass explicit
 * color props to override.
 *
 * Source: https://www.originkit.dev/components/kineticgrid
 */

export type KineticGridProps = {
  background?: string
  dotColor?: string
  lineColor?: string
  trailColor?: string
  spacing?: number
  radius?: number
  strength?: number
  trail?: boolean
  style?: CSSProperties
}

// Official propertyControls defaults — used for dark theme + as fallbacks.
const DARK_PALETTE = {
  background: '#000000',
  dotColor: '#FFFFFF',
  lineColor: '#80ACFF',
  trailColor: '#2664EB'
} as const

const PHYSICS = {
  spacing: 30,
  radius: 400,
  strength: 4,
  trail: true
} as const

type Palette = {
  background: string
  dotColor: string
  lineColor: string
  trailColor: string
}

type Point = {
  hx: number
  hy: number
  x: number
  y: number
  vx: number
  vy: number
}

type TrailPoint = { x: number; y: number; t: number }

type Cursor = { x: number; y: number; active: boolean }

function cssVar(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

/** body uses `zoom: var(--ds-ui-scale)`; layout px ≠ getBoundingClientRect px. */
function readUiScale(): number {
  const n = Number.parseFloat(
    getComputedStyle(document.documentElement).getPropertyValue('--ds-ui-scale')
  )
  return Number.isFinite(n) && n > 0 ? n : 1
}

/** Theme-aware palette; explicit prop overrides win. */
function resolvePalette(overrides: Partial<Palette>): Palette {
  const dark = document.documentElement.getAttribute('data-theme') === 'dark'
  const base: Palette = dark
    ? { ...DARK_PALETTE }
    : {
        // Light: soft sidebar board, ink dots, brand-blue mesh/trail.
        background: cssVar('--bg-sidebar', '#f0f0f0'),
        dotColor: cssVar('--text-primary', '#262626'),
        lineColor: '#5B9FFF',
        trailColor: cssVar('--ds-accent', '#0088ff')
      }
  return {
    background: overrides.background ?? base.background,
    dotColor: overrides.dotColor ?? base.dotColor,
    lineColor: overrides.lineColor ?? base.lineColor,
    trailColor: overrides.trailColor ?? base.trailColor
  }
}

export function KineticGrid({
  background: backgroundProp,
  dotColor: dotColorProp,
  lineColor: lineColorProp,
  trailColor: trailColorProp,
  spacing = PHYSICS.spacing,
  radius = PHYSICS.radius,
  strength = PHYSICS.strength,
  trail = PHYSICS.trail,
  style
}: KineticGridProps): React.ReactElement {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const cursorRef = useRef<Cursor>({ x: -9999, y: -9999, active: false })
  const trailRef = useRef<TrailPoint[]>([])
  const paletteRef = useRef<Palette>(DARK_PALETTE)

  useEffect(() => {
    const container = containerRef.current
    const canvas = canvasRef.current
    if (!container || !canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const overrides: Partial<Palette> = {
      background: backgroundProp,
      dotColor: dotColorProp,
      lineColor: lineColorProp,
      trailColor: trailColorProp
    }

    const applyPalette = (): void => {
      const next = resolvePalette(overrides)
      paletteRef.current = next
      container.style.background = next.background
    }
    applyPalette()

    const cell = Math.max(8, spacing)
    const interactRadius = Math.max(1, radius)
    const attract = (Math.max(1, Math.min(10, strength)) / 10) * 4

    let width = 1
    let height = 1
    let grid: Point[][] = []
    let points: Point[] = []

    const reduced =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches

    const rebuild = (w?: number, h?: number): void => {
      // Prefer layout px (clientWidth / RO contentRect). getBoundingClientRect is
      // post-zoom visual px and would desync the grid from cursor math.
      const scale = readUiScale()
      const rect = container.getBoundingClientRect()
      width = Math.max(
        1,
        Math.floor(w ?? (container.clientWidth || rect.width / scale))
      )
      height = Math.max(
        1,
        Math.floor(h ?? (container.clientHeight || rect.height / scale))
      )
      const dpr = window.devicePixelRatio || 1
      canvas.width = Math.floor(width * dpr)
      canvas.height = Math.floor(height * dpr)
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      grid = []
      points = []
      const cols = Math.floor(width / cell) + 2
      const rows = Math.floor(height / cell) + 2
      for (let col = 0; col < cols; col++) {
        const column: Point[] = []
        for (let row = 0; row < rows; row++) {
          const hx = col * cell
          const hy = row * cell
          const p: Point = { hx, hy, x: hx, y: hy, vx: 0, vy: 0 }
          column.push(p)
          points.push(p)
        }
        grid.push(column)
      }
    }

    const drawStatic = (): void => {
      const { dotColor, lineColor } = paletteRef.current
      ctx.clearRect(0, 0, width, height)
      ctx.globalAlpha = 0.14
      ctx.strokeStyle = lineColor
      ctx.lineWidth = 0.75
      for (let col = 0; col < grid.length; col++) {
        for (let row = 0; row < grid[col].length; row++) {
          const p = grid[col][row]
          const right = grid[col + 1]?.[row]
          const down = grid[col]?.[row + 1]
          if (right) {
            ctx.beginPath()
            ctx.moveTo(p.hx, p.hy)
            ctx.lineTo(right.hx, right.hy)
            ctx.stroke()
          }
          if (down) {
            ctx.beginPath()
            ctx.moveTo(p.hx, p.hy)
            ctx.lineTo(down.hx, down.hy)
            ctx.stroke()
          }
        }
      }
      ctx.globalAlpha = 0.4
      ctx.fillStyle = dotColor
      for (const p of points) {
        ctx.beginPath()
        ctx.arc(p.hx, p.hy, 1.2, 0, 2 * Math.PI)
        ctx.fill()
      }
      ctx.globalAlpha = 1
    }

    rebuild()

    const ro =
      typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver((entries) => {
            const cr = entries[0]?.contentRect
            rebuild(cr?.width, cr?.height)
            if (reduced) drawStatic()
          })
        : null
    ro?.observe(container)

    const themeObserver = new MutationObserver(() => {
      applyPalette()
      if (reduced) drawStatic()
    })
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme']
    })

    if (reduced) {
      drawStatic()
      return () => {
        ro?.disconnect()
        themeObserver.disconnect()
      }
    }

    /** Map viewport client coords → canvas/layout coords (undo body zoom). */
    const setCursor = (clientX: number, clientY: number): void => {
      const scale = readUiScale()
      const rect = container.getBoundingClientRect()
      const x = (clientX - rect.left) / scale
      const y = (clientY - rect.top) / scale
      cursorRef.current.x = x
      cursorRef.current.y = y
      cursorRef.current.active = true
      const t = performance.now()
      const trailPts = trailRef.current
      trailPts.push({ x, y, t })
      if (trailPts.length > 80) trailPts.shift()
    }

    const onMouseMove = (e: MouseEvent): void => setCursor(e.clientX, e.clientY)
    // pointerdown so a click/tap also seeds attraction (mousemove-only feels dead).
    const onPointerDown = (e: PointerEvent): void => setCursor(e.clientX, e.clientY)
    const onLeave = (): void => {
      cursorRef.current.active = false
      cursorRef.current.x = -9999
      cursorRef.current.y = -9999
    }
    const onTouchMove = (e: TouchEvent): void => {
      const touch = e.touches[0]
      if (touch) setCursor(touch.clientX, touch.clientY)
    }

    container.addEventListener('mousemove', onMouseMove)
    container.addEventListener('pointerdown', onPointerDown)
    container.addEventListener('mouseleave', onLeave)
    container.addEventListener('touchmove', onTouchMove, { passive: true })
    container.addEventListener('touchend', onLeave)

    let rafId = 0
    const loop = (): void => {
      const cursor = cursorRef.current
      const { dotColor, lineColor, trailColor } = paletteRef.current
      ctx.clearRect(0, 0, width, height)

      for (const p of points) {
        let ax = (p.hx - p.x) * 0.08
        let ay = (p.hy - p.y) * 0.08
        if (cursor.active) {
          const dx = cursor.x - p.x
          const dy = cursor.y - p.y
          const dist = Math.sqrt(dx * dx + dy * dy)
          if (dist < interactRadius && dist > 0.001) {
            const force = (1 - dist / interactRadius) * attract
            ax += (dx / dist) * force
            ay += (dy / dist) * force
          }
        }
        p.vx = (p.vx + ax) * 0.82
        p.vy = (p.vy + ay) * 0.82
        p.x += p.vx
        p.y += p.vy
      }

      for (let col = 0; col < grid.length; col++) {
        for (let row = 0; row < grid[col].length; row++) {
          const p = grid[col][row]
          const right = grid[col + 1]?.[row]
          const down = grid[col]?.[row + 1]
          const proximity = cursor.active
            ? Math.max(
                0,
                1 - Math.sqrt((cursor.x - p.x) ** 2 + (cursor.y - p.y) ** 2) / interactRadius
              )
            : 0
          if (right) {
            ctx.globalAlpha = 0.06 + proximity * 0.7
            ctx.strokeStyle = lineColor
            ctx.lineWidth = 0.5 + proximity * 1.5
            ctx.beginPath()
            ctx.moveTo(p.x, p.y)
            ctx.lineTo(right.x, right.y)
            ctx.stroke()
          }
          if (down) {
            ctx.globalAlpha = 0.06 + proximity * 0.7
            ctx.strokeStyle = lineColor
            ctx.lineWidth = 0.5 + proximity * 1.5
            ctx.beginPath()
            ctx.moveTo(p.x, p.y)
            ctx.lineTo(down.x, down.y)
            ctx.stroke()
          }
        }
      }

      for (const p of points) {
        const proximity = cursor.active
          ? Math.max(
              0,
              1 - Math.sqrt((cursor.x - p.x) ** 2 + (cursor.y - p.y) ** 2) / interactRadius
            )
          : 0
        ctx.globalAlpha = 0.22 + proximity * 0.78
        ctx.fillStyle = dotColor
        ctx.beginPath()
        ctx.arc(p.x, p.y, 0.8 + proximity * 2.2, 0, 2 * Math.PI)
        ctx.fill()
      }

      if (trail) {
        const now = performance.now()
        const trailPts = trailRef.current
        ctx.lineCap = 'round'
        ctx.lineJoin = 'round'
        for (let i = 1; i < trailPts.length; i++) {
          const prev = trailPts[i - 1]
          const cur = trailPts[i]
          const age = now - cur.t
          if (age > 260) continue
          ctx.globalAlpha = Math.max(0, 1 - age / 260) * 0.85
          ctx.strokeStyle = trailColor
          ctx.lineWidth = 2
          ctx.beginPath()
          ctx.moveTo(prev.x, prev.y)
          ctx.lineTo(cur.x, cur.y)
          ctx.stroke()
        }
      }

      ctx.globalAlpha = 1
      rafId = requestAnimationFrame(loop)
    }
    rafId = requestAnimationFrame(loop)

    return () => {
      cancelAnimationFrame(rafId)
      ro?.disconnect()
      themeObserver.disconnect()
      container.removeEventListener('mousemove', onMouseMove)
      container.removeEventListener('pointerdown', onPointerDown)
      container.removeEventListener('mouseleave', onLeave)
      container.removeEventListener('touchmove', onTouchMove)
      container.removeEventListener('touchend', onLeave)
    }
  }, [
    backgroundProp,
    dotColorProp,
    lineColorProp,
    trailColorProp,
    spacing,
    radius,
    strength,
    trail
  ])

  return (
    <div
      ref={containerRef}
      className="ds-startup-kinetic"
      aria-hidden
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        overflow: 'hidden',
        cursor: 'crosshair',
        ...style
      }}
    >
      <canvas
        ref={canvasRef}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          pointerEvents: 'none'
        }}
      />
    </div>
  )
}

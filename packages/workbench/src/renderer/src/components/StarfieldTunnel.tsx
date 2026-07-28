import { useEffect, useRef } from 'react'

/**
 * StarfieldTunnel — animated warp-tunnel starfield with glittering sparkle
 * flashes, used behind the startup blank board.
 *
 * Ported from a Framer "GlitterWrap" component: the Framer-specific bits
 * (RenderTarget / isStatic / prop-panel controls) are gone — in Electron we
 * always run the live rAF loop, and the tunable params below are fixed. The
 * palette is read live from the app theme so stars stay visible in both light
 * and dark, and the canvas stays transparent so the sidebar-coloured board
 * shows through.
 */

// Fixed animation params (were Framer controls). Tuned for a calm startup
// backdrop rather than the demo's aggressive defaults.
// Fixed animation params — kept identical to the original component's
// COMPONENT_DEFAULTS so the ported effect looks exactly like the source.
const CONFIG = {
  particleCount: 500,
  speed: 5, // 1–10
  density: 100, // 1–100 spawn spread
  starSize: 20, // 0–20
  focalDepth: 13, // 1–30
  turbulence: 0, // 0–10
  brightness: 100, // 0–100 %
  glitterIntensity: 3, // 0–10
  trailAmount: 100, // 0–100 %
  reverse: false
}

// Parse "#rgb" / "#rrggbb" / "rgb()" / "rgba()" into [r,g,b,a]. getComputedStyle
// resolves theme vars to one of these forms, so this covers every value we read.
function parseColor(input: string): [number, number, number, number] {
  if (!input) return [255, 255, 255, 1]
  const s = input.trim()
  if (s.startsWith('#')) {
    let hex = s.slice(1)
    if (hex.length === 3) {
      hex = hex
        .split('')
        .map((c) => c + c)
        .join('')
    }
    const num = parseInt(hex, 16)
    return [(num >> 16) & 255, (num >> 8) & 255, num & 255, 1]
  }
  const m = s.match(/rgba?\(([^)]+)\)/i)
  if (m) {
    const parts = m[1].split(',').map((p) => parseFloat(p.trim()))
    return [parts[0] || 0, parts[1] || 0, parts[2] || 0, parts[3] == null ? 1 : parts[3]]
  }
  return [255, 255, 255, 1]
}

/**
 * Read a 3-colour palette from the live theme. `--text-primary` reads clearly
 * against any board background; `--ds-accent` adds a branded tint; a mix of the
 * two gives a third. Falls back to a neutral trio if a var is missing.
 */
function readThemePalette(el: HTMLElement): [number, number, number, number][] {
  const cs = getComputedStyle(el)
  const text = parseColor(cs.getPropertyValue('--text-primary').trim() || '#262626')
  const accent = parseColor(cs.getPropertyValue('--ds-accent').trim() || '#0088ff')
  // Third tone: halfway between the two, so the field reads as one hue family.
  const blend: [number, number, number, number] = [
    Math.round((text[0] + accent[0]) / 2),
    Math.round((text[1] + accent[1]) / 2),
    Math.round((text[2] + accent[2]) / 2),
    1
  ]
  return [text, accent, blend]
}

type Star = {
  x: number
  y: number
  z: number
  px: number
  py: number
  seed: number
  vmul: number
  colorIdx: number
  flashUntil: number
  nextFlash: number
}

export function StarfieldTunnel(): React.ReactElement {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const container = containerRef.current
    const canvas = canvasRef.current
    if (!container || !canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const stars: Star[] = []
    let elapsed = 0
    let lastT = performance.now()
    let rafId: number | null = null

    const sizeRef = { w: 0, h: 0, dpr: 1 }

    // Live palette + rgb strings, refreshed when the theme changes.
    let palette = readThemePalette(container)
    let rgbStrs = palette.map((c) => `rgb(${c[0]}, ${c[1]}, ${c[2]})`)
    const refreshPalette = (): void => {
      palette = readThemePalette(container)
      rgbStrs = palette.map((c) => `rgb(${c[0]}, ${c[1]}, ${c[2]})`)
    }

    // Map UI-style params to the physics/render working ranges once.
    const cfg = {
      reverse: CONFIG.reverse,
      density: CONFIG.density,
      stepZ: CONFIG.speed * 0.0008,
      focalDepth: CONFIG.focalDepth / 100,
      starScale: CONFIG.starSize * 0.15,
      turbulence: CONFIG.turbulence * 0.2,
      glitter: CONFIG.glitterIntensity * 0.1,
      brightness: Math.min(1, CONFIG.brightness / 100),
      trail: CONFIG.trailAmount / 100
    }

    const resetStar = (s: Star, initial = false): void => {
      const angle = Math.random() * Math.PI * 2
      const radius = (0.2 + Math.random() * 0.8) * (cfg.density / 15)
      s.x = Math.cos(angle) * radius
      s.y = Math.sin(angle) * radius
      if (cfg.reverse) {
        s.z = initial ? cfg.focalDepth + Math.random() * (1 - cfg.focalDepth) : cfg.focalDepth
      } else {
        s.z = initial ? Math.random() : 1.0
      }
      s.px = NaN
      s.py = NaN
      s.seed = Math.random() * 1000
      s.vmul = 0.6 + Math.random() * 0.8
      s.colorIdx = Math.floor(Math.random() * 3)
      s.flashUntil = 0
      s.nextFlash = elapsed + 1 + Math.random() * 4 * (1 / Math.max(0.0001, cfg.glitter))
    }

    const makeStar = (): Star => ({
      x: 0,
      y: 0,
      z: 0,
      px: NaN,
      py: NaN,
      seed: 0,
      vmul: 1,
      colorIdx: 0,
      flashUntil: 0,
      nextFlash: 0
    })

    for (let i = 0; i < Math.max(1, Math.floor(CONFIG.particleCount)); i++) {
      const s = makeStar()
      resetStar(s, true)
      stars.push(s)
    }

    const resize = (entry?: ResizeObserverEntry): void => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const cr = entry?.contentRect
      const rectW = cr?.width || container.clientWidth || container.getBoundingClientRect().width
      const rectH = cr?.height || container.clientHeight || container.getBoundingClientRect().height
      const w = Math.max(1, Math.floor(rectW) || 600)
      const h = Math.max(1, Math.floor(rectH) || 400)

      const prev = sizeRef
      if (prev.w === w && prev.h === h && prev.dpr === dpr) return

      sizeRef.w = w
      sizeRef.h = h
      sizeRef.dpr = dpr
      canvas.width = Math.floor(w * dpr)
      canvas.height = Math.floor(h * dpr)
      canvas.style.width = `${w}px`
      canvas.style.height = `${h}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
    }

    resize()
    const ro = new ResizeObserver((entries) => resize(entries[0]))
    ro.observe(container)

    const drawFrame = (deltaSec: number): void => {
      const { reverse, stepZ, focalDepth, starScale, turbulence, glitter, brightness, trail } = cfg

      const { w, h } = sizeRef
      const cx = w / 2
      const cy = h / 2
      const projScale = Math.min(w, h) * 0.9

      const dt = Math.max(0.001, Math.min(0.1, deltaSec)) * 60

      // Framerate-independent trail decay via destination-out erase.
      const keep = Math.pow(Math.min(0.98, Math.max(0, trail)), dt)
      const trailAlpha = Math.max(0.02, 1 - keep)
      ctx.globalAlpha = 1
      ctx.globalCompositeOperation = 'destination-out'
      ctx.fillStyle = `rgba(0, 0, 0, ${trailAlpha})`
      ctx.fillRect(0, 0, w, h)

      ctx.globalCompositeOperation = 'lighter'

      for (let i = 0; i < stars.length; i++) {
        const s = stars[i]

        const vz = stepZ * s.vmul * dt
        if (reverse) {
          s.z += vz
          if (s.z >= 1.0) {
            resetStar(s)
            continue
          }
        } else {
          s.z -= vz
          if (s.z <= focalDepth) {
            resetStar(s)
            continue
          }
        }

        let tx = s.x
        let ty = s.y
        if (turbulence > 0) {
          const t = elapsed * 1.2 + s.seed
          const amp = turbulence * (1 - s.z) * 0.25
          tx += Math.sin(t + s.seed) * amp
          ty += Math.cos(t * 1.13 + s.seed * 0.7) * amp
        }

        const persp = focalDepth / Math.max(s.z, 0.0001)
        const sx = cx + tx * persp * projScale
        const sy = cy + ty * persp * projScale

        if (!reverse && (sx < -20 || sx > w + 20 || sy < -20 || sy > h + 20)) {
          resetStar(s)
          continue
        }

        let flashMult = 1
        if (glitter > 0) {
          if (elapsed >= s.nextFlash && s.flashUntil < elapsed) {
            s.flashUntil = elapsed + 0.04 + Math.random() * 0.07
            s.nextFlash = elapsed + 1 + Math.random() * 4 * (1 / Math.max(0.0001, glitter))
          }
          if (elapsed <= s.flashUntil) {
            flashMult = 1 + 2.5 * glitter
          }
        }

        const sizePersp = Math.min(2.5, (focalDepth / Math.max(s.z, 0.0001)) * 0.6)
        const baseR = Math.max(0.25, starScale * (0.4 + sizePersp))
        const maxR = 1 + starScale * 2.5
        const r = Math.min(baseR * flashMult, maxR)

        const lifeT = reverse ? s.z : 1 - s.z
        const fadeIn = reverse
          ? Math.min(1, (s.z - focalDepth) / (1 - focalDepth) / 0.12)
          : 1
        const a =
          Math.min(1, reverse ? 0.85 - lifeT * 0.6 : lifeT * 0.9 + 0.05) *
          fadeIn *
          brightness *
          (flashMult > 1 ? 1 : 0.85)

        const colStr = rgbStrs[s.colorIdx]

        if (!Number.isNaN(s.px) && !Number.isNaN(s.py)) {
          ctx.globalAlpha = a * 0.5
          ctx.strokeStyle = colStr
          ctx.lineWidth = Math.max(0.4, r * 0.4)
          ctx.beginPath()
          ctx.moveTo(s.px, s.py)
          ctx.lineTo(sx, sy)
          ctx.stroke()
        }

        ctx.globalAlpha = a
        ctx.fillStyle = colStr
        ctx.fillRect(sx - r, sy - r, r * 2, r * 2)

        if (flashMult > 1) {
          const rf = Math.min(r * 1.4, maxR * 1.4)
          ctx.globalAlpha = a * 0.5
          ctx.fillRect(sx - rf, sy - rf, rf * 2, rf * 2)
        }

        s.px = sx
        s.py = sy
      }

      ctx.globalAlpha = 1
      ctx.globalCompositeOperation = 'source-over'
      elapsed += Math.min(0.1, Math.max(0, deltaSec))
    }

    const reduced =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches

    if (reduced) {
      // Honour reduced-motion: render one warm static field, no rAF loop.
      for (let i = 0; i < 60; i++) drawFrame(1 / 60)
      return () => ro.disconnect()
    }

    const loop = (t: number): void => {
      const deltaSec = (t - lastT) / 1000
      lastT = t
      drawFrame(deltaSec)
      rafId = requestAnimationFrame(loop)
    }
    lastT = performance.now()
    rafId = requestAnimationFrame(loop)

    // Re-read palette if the theme (data-theme attr) flips mid-animation.
    const themeObserver = new MutationObserver(refreshPalette)
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme']
    })

    return () => {
      if (rafId != null) cancelAnimationFrame(rafId)
      ro.disconnect()
      themeObserver.disconnect()
    }
  }, [])

  return (
    <div ref={containerRef} className="ds-startup-starfield" aria-hidden>
      <canvas ref={canvasRef} />
    </div>
  )
}

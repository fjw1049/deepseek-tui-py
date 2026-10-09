import { useCallback, useEffect, useRef, type ReactElement } from 'react'

type Input = Record<string, unknown>
export function BrowserViewport({ image, enabled, resizeEnabled = enabled, inspect = false, onInspectCancel, generation, width, height, label, send, onError }: {
  image: string; enabled: boolean; inspect?: boolean; onInspectCancel?: () => void; resizeEnabled?: boolean; generation: number; width: number; height: number; label: string
  send: (input: Input) => Promise<{ text?: string }>; onError: (message: string) => void
}): ReactElement {
  const surface = useRef<HTMLDivElement>(null)
  const field = useRef<HTMLTextAreaElement>(null)
  const queue = useRef(Promise.resolve())
  const composing = useRef(false)
  const mounted = useRef(true)
  const moveAt = useRef(0)
  const click = useRef({ time: 0, x: 0, y: 0, count: 0 })
  const current = useRef({ enabled, generation, send, onError, inspect })
  current.current = { enabled, generation, send, onError, inspect }
  const enqueue = useCallback((input: Input): void => {
    const token = current.current.generation
    queue.current = queue.current.then(async () => {
      if (!mounted.current || !current.current.enabled || current.current.generation !== token) return
      if (current.current.inspect && !['pick', 'wheel', 'resize'].includes(String(input.kind))) return
      if (input.kind === 'pick' && !current.current.inspect) return
      const result = await current.current.send({ ...input, kind: input.kind === 'cut' ? 'copy' : input.kind, generation: token })
      if (typeof result.text === 'string' && result.text) {
        await navigator.clipboard.writeText(result.text)
        if (mounted.current && input.kind === 'cut' && current.current.enabled && current.current.generation === token) {
          await current.current.send({ kind: 'cut', text: result.text, generation: token })
        }
      }
    }).catch((e: Error) => { if (mounted.current) current.current.onError(e.message) })
  }, [])
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => { if (!enabled) { field.current?.blur(); if (field.current) field.current.value = '' } }, [enabled])
  useEffect(() => {
    const target = surface.current
    if (!target || !resizeEnabled) return
    let timer: ReturnType<typeof setTimeout>
    const observer = new ResizeObserver(([entry]) => {
      clearTimeout(timer)
      timer = setTimeout(() => {
        const w = Math.max(320, Math.min(2400, Math.round(entry.contentRect.width)))
        const h = Math.max(240, Math.min(1600, Math.round(entry.contentRect.height)))
        if (w !== width || h !== height) enqueue({ kind: 'resize', width: w, height: h })
      }, 180)
    })
    observer.observe(target)
    return () => { observer.disconnect(); clearTimeout(timer) }
  }, [resizeEnabled, generation, width, height, enqueue])
  useEffect(() => {
    const target = surface.current
    if (!target || !enabled) return
    const preventScroll = (event: WheelEvent): void => event.preventDefault()
    target.addEventListener('wheel', preventScroll, { passive: false })
    return () => target.removeEventListener('wheel', preventScroll)
  }, [enabled])
  const point = (event: { clientX: number; clientY: number }): { x: number; y: number } | null => {
    const rect = surface.current!.getBoundingClientRect()
    const scale = Math.min(rect.width / width, rect.height / height)
    const x = (event.clientX - rect.left - (rect.width - width * scale) / 2) / scale
    const y = (event.clientY - rect.top - (rect.height - height * scale) / 2) / scale
    return x >= 0 && y >= 0 && x < width && y < height ? { x, y } : null
  }
  const modifiers = (e: { altKey: boolean; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean }): number =>
    (e.altKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.metaKey ? 4 : 0) | (e.shiftKey ? 8 : 0)
  return <div ref={surface} className="ds-browser-viewport" style={inspect ? { cursor: 'crosshair' } : undefined} onContextMenu={(e) => e.preventDefault()}
    onPointerDown={(e) => {
      if (!enabled) return
      const p = point(e); if (!p) return
      e.preventDefault()
      if (field.current) {
        const rect = e.currentTarget.getBoundingClientRect()
        field.current.style.left = `${e.clientX - rect.left}px`
        field.current.style.top = `${e.clientY - rect.top}px`
        field.current.focus({ preventScroll: true })
      }
      e.currentTarget.setPointerCapture?.(e.pointerId)
      const previous = click.current
      const count = Date.now() - previous.time < 400 && Math.hypot(p.x - previous.x, p.y - previous.y) < 6 ? previous.count % 3 + 1 : 1
      click.current = { ...p, time: Date.now(), count }
      if (inspect) return
      enqueue({ kind: 'mouse', event: 'mousePressed', ...p, button: ['left', 'middle', 'right'][e.button] ?? 'left', buttons: e.buttons, clicks: count, modifiers: modifiers(e) })
    }}
    onPointerMove={(e) => {
      if (!enabled || inspect || Date.now() - moveAt.current < 40) return
      const p = point(e); if (!p) return
      moveAt.current = Date.now()
      enqueue({ kind: 'mouse', event: 'mouseMoved', ...p, buttons: e.buttons, modifiers: modifiers(e) })
    }}
    onPointerUp={(e) => {
      if (!enabled) return
      const p = point(e) ?? { x: click.current.x, y: click.current.y }
      if (inspect) { if (e.button === 0 && point(e)) enqueue({ kind: 'pick', ...p }); return }
      enqueue({ kind: 'mouse', event: 'mouseReleased', ...p, button: ['left', 'middle', 'right'][e.button] ?? 'left', buttons: 0, clicks: click.current.count, modifiers: modifiers(e) })
      if (e.currentTarget.hasPointerCapture?.(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId)
    }}
    onPointerCancel={() => { if (enabled && !inspect) enqueue({ kind: 'mouse', event: 'mouseReleased', x: click.current.x, y: click.current.y, button: 'left', buttons: 0 }) }}
    onWheel={(e) => {
      if (!enabled) return
      const p = point(e); if (!p) return
      enqueue({ kind: 'wheel', ...p, delta_x: Math.max(-5000, Math.min(5000, e.deltaX * (e.deltaMode === 1 ? 16 : 1))), delta_y: Math.max(-5000, Math.min(5000, e.deltaY * (e.deltaMode === 1 ? 16 : 1))), modifiers: modifiers(e) })
    }}>
    <img src={image} alt={label} draggable={false} />
    <textarea ref={field} className="ds-browser-input" aria-label={label} disabled={!enabled} autoComplete="off" autoCapitalize="off" spellCheck={false}
      onCompositionStart={() => { composing.current = true }}
      onCompositionEnd={(e) => { composing.current = false; if (e.currentTarget.value) enqueue({ kind: 'text', text: e.currentTarget.value }); e.currentTarget.value = '' }}
      onInput={(e) => { if (composing.current) return; if (e.currentTarget.value) enqueue({ kind: 'text', text: e.currentTarget.value }); e.currentTarget.value = '' }}
      onPaste={(e) => { e.preventDefault(); enqueue({ kind: 'text', text: e.clipboardData.getData('text/plain') }) }}
      onKeyDown={(e) => {
        if (inspect) { e.preventDefault(); if (e.key === 'Escape') onInspectCancel?.(); return }
        if (e.nativeEvent.isComposing || composing.current || e.keyCode === 229) return
        if ((e.ctrlKey || e.metaKey) && ['c', 'x'].includes(e.key.toLowerCase())) { e.preventDefault(); enqueue({ kind: e.key.toLowerCase() === 'c' ? 'copy' : 'cut' }); return }
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'v') return
        if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) return
        e.preventDefault(); enqueue({ kind: 'key', event: 'keyDown', key: e.key, code: e.code, key_code: e.keyCode, modifiers: modifiers(e) })
      }}
      onKeyUp={(e) => {
        if (inspect || composing.current || (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey)) return
        if ((e.ctrlKey || e.metaKey) && ['c', 'x', 'v'].includes(e.key.toLowerCase())) return
        enqueue({ kind: 'key', event: 'keyUp', key: e.key, code: e.code, key_code: e.keyCode, modifiers: modifiers(e) })
      }} />
  </div>
}

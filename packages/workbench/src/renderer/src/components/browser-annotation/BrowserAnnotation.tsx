import { useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState, type ReactElement, type ReactNode, type Ref, type PointerEvent as ReactPointerEvent } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ANNOTATION_FONT, DEFAULT_ANNOTATION_COLOR, DEFAULT_ANNOTATION_WIDTH, EMPTY_ANNOTATION_HISTORY, TEXT_LINE_HEIGHT,
  clearMarks, commitMark, compositeAnnotation, drawMark, fitContain, hasHistory, redoMark, textSizeFor, undoMark,
  type AnnotationMark, type AnnotationTool, type PenMark, type Point, type ShapeMark, type TextMark
} from '../../lib/browser-annotation'
import { ConfirmDialog } from '../workspace-editor/ConfirmDialog'
import { AnnotationToolbar } from './AnnotationToolbar'

type Size = { width: number; height: number }
type TextDraft = { id: number; x: number; y: number; value: string; size: number; color: string }
type Backdrop = { url: string; natural: Size | null; pageUrl?: string }

export type BrowserAnnotationHandle = {
  /** The header's select-element button: same as the bar's cursor, including the discard check. */
  togglePick: () => void
}

function textMark(draft: TextDraft): TextMark | null {
  const text = draft.value.trimEnd()
  return text.trim() ? { kind: 'text', x: draft.x, y: draft.y, text, size: draft.size, color: draft.color } : null
}

/** The UI scale (body zoom) between client pixels and the element's own layout pixels. */
function layoutZoom(element: HTMLElement): number {
  const box = element.getBoundingClientRect()
  return box.width && element.offsetWidth ? box.width / element.offsetWidth : 1
}

/**
 * The browser pane's annotation bar. At rest it waits on the live page; the cursor hands the page
 * to the element picker; any drawing tool freezes a screenshot and draws over it until the marks
 * are added to the chat. Picking is owned by the pane, which runs the picker.
 */
export function BrowserAnnotation({ disabled, pickEnabled, picking, onPickingChange, capture, onAdd, onHide, onError, status, activity, tools, closable, collapsed = false, pageUrl, ref }: {
  collapsed?: boolean
  disabled: boolean
  pickEnabled: boolean
  picking: boolean
  onPickingChange: (picking: boolean) => void
  /** Resolves to an image data URL of the page as shown; rejects with a user-facing message. */
  capture: () => Promise<string>
  /** Resolves false when the image was not attached; the sketch then stays open. */
  onAdd: (file: File, annotated: boolean, pageUrl?: string) => Promise<boolean>
  /** Source URL frozen with the screenshot, even if the live tab later navigates. */
  pageUrl?: string
  /** Hides the resting bar. */
  onHide: () => void
  onError: (message: string) => void
  /** Who controls the page, shown on the resting bar. */
  status?: ReactNode
  activity?: ReactNode
  /** More resting tools after the annotation tools (demonstrate to the agent). */
  tools?: ReactNode
  /** False while the resting bar must stay up. */
  closable?: boolean
  ref?: Ref<BrowserAnnotationHandle>
}): ReactElement {
  const { t } = useTranslation()
  const [tool, setTool] = useState<AnnotationTool | null>(null)
  const [backdrop, setBackdrop] = useState<Backdrop | null>(null)
  const [history, setHistory] = useState(EMPTY_ANNOTATION_HISTORY)
  const [color, setColor] = useState<string>(DEFAULT_ANNOTATION_COLOR)
  const [width, setWidth] = useState<number>(DEFAULT_ANNOTATION_WIDTH)
  const [text, setTextState] = useState<TextDraft | null>(null)
  const [confirm, setConfirm] = useState<'close' | 'pick' | null>(null)
  const [adding, setAdding] = useState(false)
  const [area, setArea] = useState<Size>({ width: 0, height: 0 })
  const root = useRef<HTMLDivElement>(null)
  const stage = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const textRef = useRef<TextDraft | null>(null)
  const draft = useRef<{ pointerId: number; mark: PenMark | ShapeMark } | null>(null)
  /** Marks are stored in the frame's layout pixels as first laid out; later resizes only rescale the view. */
  const base = useRef<Size | null>(null)
  const captureRun = useRef(0)
  const textIds = useRef(0)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false; captureRun.current += 1 }
  }, [])

  const sketching = tool !== null
  const barState = sketching ? 'sketch' : picking ? 'pick' : 'rest'
  const setText = (next: TextDraft | null): void => { textRef.current = next; setTextState(next) }
  const commitText = (): void => {
    const current = textRef.current
    if (!current) return
    setText(null)
    const mark = textMark(current)
    if (mark) setHistory(h => commitMark(h, mark))
  }
  const hasMarks = history.present.length > 0 || !!textRef.current?.value.trim()

  const leaveSketch = (): void => {
    captureRun.current += 1
    draft.current = null; base.current = null
    setText(null); setTool(null); setBackdrop(null); setHistory(EMPTY_ANNOTATION_HISTORY); setConfirm(null)
  }
  const togglePick = (): void => {
    if (!sketching) { onPickingChange(!picking); return }
    if (hasMarks) { setConfirm('pick'); return }
    leaveSketch(); onPickingChange(true)
  }
  useImperativeHandle(ref, () => ({ togglePick }))
  const chooseTool = (next: AnnotationTool): void => {
    if (picking) onPickingChange(false)
    commitText()
    setTool(next)
  }
  const requestClose = (): void => {
    if (sketching) { if (hasMarks) setConfirm('close'); else leaveSketch() }
    else if (picking) onPickingChange(false)
    else onHide()
  }
  const discard = (): void => {
    const then = confirm
    leaveSketch()
    if (then === 'pick') onPickingChange(true)
  }

  const startCapture = useCallback((): void => {
    const run = ++captureRun.current
    capture().then(url => {
      if (run === captureRun.current) setBackdrop({ url, natural: null, pageUrl })
    }, (error: unknown) => {
      if (run !== captureRun.current) return
      onError(error instanceof Error && error.message ? error.message : t('annotationCaptureFailed'))
      setTool(null)
    })
  }, [capture, onError, t, pageUrl])
  // The first drawing tool freezes the page; switching tools keeps the same screenshot.
  useEffect(() => { if (sketching && !backdrop) startCapture() }, [sketching, backdrop === null]) // eslint-disable-line react-hooks/exhaustive-deps

  useLayoutEffect(() => {
    const element = stage.current
    if (!element) return
    const measure = (): void => {
      const box = element.getBoundingClientRect()
      const zoom = layoutZoom(element)
      const next = { width: box.width / zoom, height: box.height / zoom }
      setArea(current => current.width === next.width && current.height === next.height ? current : next)
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [sketching])

  const frame = backdrop?.natural ? fitContain(backdrop.natural, area) : null
  if (frame && frame.width > 0 && !base.current) base.current = { width: frame.width, height: frame.height }
  const ratio = frame && base.current ? frame.width / base.current.width : 1

  const redraw = useCallback((): void => {
    const element = canvas.current
    if (!element || !frame || !base.current) return
    const scale = (window.devicePixelRatio || 1) * layoutZoom(element)
    const pixelWidth = Math.round(frame.width * scale), pixelHeight = Math.round(frame.height * scale)
    if (element.width !== pixelWidth) element.width = pixelWidth
    if (element.height !== pixelHeight) element.height = pixelHeight
    let ctx: CanvasRenderingContext2D | null = null
    try { ctx = element.getContext('2d') } catch { /* no canvas support (tests) */ }
    if (!ctx) return
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.clearRect(0, 0, element.width, element.height)
    ctx.setTransform(scale * ratio, 0, 0, scale * ratio, 0, 0)
    for (const mark of history.present) drawMark(ctx, mark)
    if (draft.current) drawMark(ctx, draft.current.mark)
  }, [frame?.width, frame?.height, ratio, history.present]) // eslint-disable-line react-hooks/exhaustive-deps
  useLayoutEffect(redraw, [redraw])

  useEffect(() => { if (backdrop) root.current?.focus({ preventScroll: true }) }, [backdrop])

  const point = (e: ReactPointerEvent<HTMLElement>): Point => {
    const box = e.currentTarget.getBoundingClientRect()
    const zoom = layoutZoom(e.currentTarget)
    return { x: (e.clientX - box.left) / zoom / ratio, y: (e.clientY - box.top) / zoom / ratio }
  }
  const onPointerDown = (e: ReactPointerEvent<HTMLCanvasElement>): void => {
    if (e.button !== 0 || !tool || adding) return
    const p = point(e)
    if (tool === 'text') {
      e.preventDefault()
      commitText()
      setText({ id: ++textIds.current, x: p.x, y: p.y, value: '', size: textSizeFor(width), color })
      return
    }
    if (draft.current) return
    try { e.currentTarget.setPointerCapture(e.pointerId) } catch { /* pointer already gone */ }
    draft.current = { pointerId: e.pointerId, mark: tool === 'pen'
      ? { kind: 'pen', points: [p], color, width }
      : { kind: tool, x1: p.x, y1: p.y, x2: p.x, y2: p.y, color, width } }
    redraw()
  }
  const onPointerMove = (e: ReactPointerEvent<HTMLCanvasElement>): void => {
    const current = draft.current
    if (!current || current.pointerId !== e.pointerId) return
    const p = point(e)
    const mark = current.mark
    if (mark.kind === 'pen') mark.points.push(p)
    else if (e.shiftKey && mark.kind !== 'arrow') {
      const side = Math.max(Math.abs(p.x - mark.x1), Math.abs(p.y - mark.y1))
      mark.x2 = mark.x1 + Math.sign(p.x - mark.x1 || 1) * side
      mark.y2 = mark.y1 + Math.sign(p.y - mark.y1 || 1) * side
    } else { mark.x2 = p.x; mark.y2 = p.y }
    redraw()
  }
  const onPointerEnd = (e: ReactPointerEvent<HTMLCanvasElement>): void => {
    const current = draft.current
    if (!current || current.pointerId !== e.pointerId) return
    draft.current = null
    const next = commitMark(history, current.mark)
    if (next === history) redraw(); else setHistory(next)
  }

  const add = async (): Promise<void> => {
    if (!backdrop || !base.current || adding) return
    const pending = textRef.current ? textMark(textRef.current) : null
    const marks: AnnotationMark[] = pending ? [...history.present, pending] : history.present
    commitText()
    setAdding(true)
    try {
      const blob = await compositeAnnotation(backdrop.url, marks, base.current)
      const annotated = marks.length > 0
      const attached = await onAdd(new File([blob], annotated ? 'browser-annotation.png' : 'browser-screenshot.png', { type: 'image/png' }), annotated, backdrop.pageUrl)
      if (attached && alive.current) leaveSketch()
    } catch (error) {
      if (alive.current) onError(error instanceof Error ? error.message : String(error))
    } finally {
      if (alive.current) setAdding(false)
    }
  }

  return <div ref={root} className={`ds-annotation${collapsed ? ' is-collapsed' : ''}`} aria-hidden={collapsed || undefined} inert={collapsed} tabIndex={-1}
    onKeyDown={(e) => {
      if (e.defaultPrevented || confirm) return
      if (e.key === 'Escape' && barState !== 'rest') { e.preventDefault(); requestClose(); return }
      if (sketching && (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        setHistory(h => e.shiftKey ? redoMark(h) : undoMark(h))
      }
    }}>
    {sketching ? <div ref={stage} className="ds-annotation__stage">
      {backdrop ? <div className="ds-annotation__frame" style={frame ? { left: frame.left, top: frame.top, width: frame.width, height: frame.height } : undefined}>
        <img className="ds-annotation__backdrop" src={backdrop.url} alt="" draggable={false}
          onLoad={(e) => {
            const { naturalWidth, naturalHeight } = e.currentTarget
            const loaded = backdrop.url
            setBackdrop(current => current?.url === loaded ? { ...current, natural: { width: naturalWidth, height: naturalHeight } } : current)
          }} />
        <canvas ref={canvas} className={`ds-annotation__canvas is-${tool}`} role="img" aria-label={t('annotationCanvas')}
          onPointerDown={onPointerDown} onMouseDown={(e) => { if (tool === 'text') e.preventDefault() }}
          onPointerMove={onPointerMove} onPointerUp={onPointerEnd} onPointerCancel={onPointerEnd} onLostPointerCapture={onPointerEnd} />
        {text ? <textarea key={text.id} className="ds-annotation__text" autoFocus aria-label={t('annotationTextLabel')} value={text.value}
          rows={text.value.split('\n').length}
          style={{ left: text.x * ratio, top: text.y * ratio, color: text.color, fontSize: text.size * ratio, lineHeight: TEXT_LINE_HEIGHT, fontFamily: ANNOTATION_FONT }}
          onChange={(e) => setText({ ...text, value: e.target.value })}
          onBlur={() => { if (textRef.current?.id === text.id) commitText() }}
          onPointerDown={(e) => e.stopPropagation()}
          onKeyDown={(e) => {
            e.stopPropagation()
            if (e.nativeEvent.isComposing || e.keyCode === 229) return
            if (e.key === 'Escape') { e.preventDefault(); setText(null); root.current?.focus({ preventScroll: true }) }
            else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); commitText(); root.current?.focus({ preventScroll: true }) }
          }} />
        : null}
      </div> : <div className="ds-annotation__capturing" role="status">{t('annotationCapturing')}</div>}
    </div> : null}
    <AnnotationToolbar state={barState} status={status} activity={activity} tools={tools} closable={closable} tool={tool} disabled={disabled} pickEnabled={pickEnabled} color={color} width={width}
      canUndo={history.past.length > 0} canRedo={history.future.length > 0} canClear={history.present.length > 0}
      showHistory={sketching && hasHistory(history)} canAdd={sketching && !!backdrop} adding={adding}
      onPick={togglePick} onTool={chooseTool} onColorChange={setColor} onWidthChange={setWidth}
      onUndo={() => setHistory(undoMark)} onRedo={() => setHistory(redoMark)} onClear={() => { setText(null); setHistory(clearMarks) }}
      onAdd={() => void add()} onClose={requestClose} />
    {confirm ? <ConfirmDialog title={t('annotationDiscardTitle')} body={t('annotationDiscardBody')} confirmLabel={t('annotationDiscard')}
      cancelLabel={t('annotationKeepEditing')} destructive onConfirm={discard} onCancel={() => setConfirm(null)} /> : null}
  </div>
}

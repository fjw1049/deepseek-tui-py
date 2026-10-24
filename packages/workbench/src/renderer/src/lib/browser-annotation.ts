/**
 * Browser annotation marks: a vector model drawn over a frozen page screenshot,
 * then composited at the screenshot's native resolution for the chat.
 */

import { formatComposerPathMention } from './composer-insert'

export type AnnotationShape = 'rect' | 'ellipse' | 'arrow'
export type AnnotationTool = 'pen' | 'text' | AnnotationShape

export const ANNOTATION_SHAPES: readonly AnnotationShape[] = ['rect', 'ellipse', 'arrow']
export const ANNOTATION_COLORS = ['#E03131', '#1971C2', '#2F9E44', '#1F1E1D', '#FFFFFF'] as const
export const ANNOTATION_WIDTHS = [2, 4, 8, 12] as const
export const DEFAULT_ANNOTATION_COLOR = ANNOTATION_COLORS[0]
export const DEFAULT_ANNOTATION_WIDTH = ANNOTATION_WIDTHS[1]
/** Shapes smaller than this (CSS px) are stray clicks, not marks. */
export const MIN_SHAPE_SIZE = 4
export const ANNOTATION_FONT = '-apple-system, BlinkMacSystemFont, "PingFang SC", "Segoe UI", sans-serif'

export type Point = { x: number; y: number }
export type PenMark = { kind: 'pen'; points: Point[]; color: string; width: number }
export type ShapeMark = { kind: AnnotationShape; x1: number; y1: number; x2: number; y2: number; color: string; width: number }
export type TextMark = { kind: 'text'; x: number; y: number; text: string; size: number; color: string }
export type AnnotationMark = PenMark | ShapeMark | TextMark

/** Text grows with the chosen stroke so one picker sizes both. */
export function textSizeFor(width: number): number {
  return width <= 2 ? 14 : width <= 4 ? 18 : width <= 8 ? 24 : 32
}

/** Pens always count (a click is a dot); shapes need some extent; text needs content. */
export function isMeaningfulMark(mark: AnnotationMark): boolean {
  if (mark.kind === 'pen') return mark.points.length > 0
  if (mark.kind === 'text') return mark.text.trim().length > 0
  if (mark.kind === 'arrow') return Math.hypot(mark.x2 - mark.x1, mark.y2 - mark.y1) >= MIN_SHAPE_SIZE
  return Math.abs(mark.x2 - mark.x1) >= MIN_SHAPE_SIZE && Math.abs(mark.y2 - mark.y1) >= MIN_SHAPE_SIZE
}

export type AnnotationHistory = { past: AnnotationMark[][]; present: AnnotationMark[]; future: AnnotationMark[][] }
export const EMPTY_ANNOTATION_HISTORY: AnnotationHistory = { past: [], present: [], future: [] }

export function commitMark(history: AnnotationHistory, mark: AnnotationMark): AnnotationHistory {
  if (!isMeaningfulMark(mark)) return history
  return { past: [...history.past, history.present], present: [...history.present, mark], future: [] }
}

export function undoMark(history: AnnotationHistory): AnnotationHistory {
  const previous = history.past.at(-1)
  if (!previous) return history
  return { past: history.past.slice(0, -1), present: previous, future: [history.present, ...history.future] }
}

export function redoMark(history: AnnotationHistory): AnnotationHistory {
  const [next, ...future] = history.future
  if (!next) return history
  return { past: [...history.past, history.present], present: next, future }
}

/** Clearing is one undoable step, like any other edit. */
export function clearMarks(history: AnnotationHistory): AnnotationHistory {
  if (!history.present.length) return history
  return { past: [...history.past, history.present], present: [], future: [] }
}

export function hasHistory(history: AnnotationHistory): boolean {
  return history.past.length > 0 || history.present.length > 0 || history.future.length > 0
}

const BAR_SHOWN_KEY = 'ds-browser-annotation-bar-shown'

/** The resting annotation bar is shown until the user hides it; the choice persists. */
export function readAnnotationBarShown(): boolean {
  try { return window.localStorage.getItem(BAR_SHOWN_KEY) !== 'false' } catch { return true }
}

export function writeAnnotationBarShown(shown: boolean): void {
  try { window.localStorage.setItem(BAR_SHOWN_KEY, String(shown)) } catch { /* storage unavailable */ }
}

/** The subset of CanvasRenderingContext2D the marks use, so tests can record calls. */
export type AnnotationContext = Pick<CanvasRenderingContext2D,
  'beginPath' | 'moveTo' | 'lineTo' | 'stroke' | 'fill' | 'arc' | 'ellipse' | 'strokeRect' | 'closePath' | 'fillText'> & {
  lineCap: CanvasLineCap; lineJoin: CanvasLineJoin; lineWidth: number
  strokeStyle: string | CanvasGradient | CanvasPattern; fillStyle: string | CanvasGradient | CanvasPattern
  font: string; textBaseline: CanvasTextBaseline
}

export const TEXT_LINE_HEIGHT = 1.2

/** Arrow geometry: the head is a triangle at (x2, y2); the shaft stops inside it so round caps don't poke through. */
export function arrowGeometry(mark: ShapeMark): { shaftEnd: Point; head: [Point, Point, Point] } {
  const length = Math.hypot(mark.x2 - mark.x1, mark.y2 - mark.y1)
  const ux = length ? (mark.x2 - mark.x1) / length : 1
  const uy = length ? (mark.y2 - mark.y1) / length : 0
  const head = Math.min(Math.max(mark.width * 4, 10), length)
  const half = head / 2
  const base = { x: mark.x2 - ux * head, y: mark.y2 - uy * head }
  return {
    shaftEnd: { x: mark.x2 - ux * head * 0.7, y: mark.y2 - uy * head * 0.7 },
    head: [{ x: mark.x2, y: mark.y2 }, { x: base.x + uy * half, y: base.y - ux * half }, { x: base.x - uy * half, y: base.y + ux * half }]
  }
}

export function drawMark(ctx: AnnotationContext, mark: AnnotationMark): void {
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.strokeStyle = mark.color
  ctx.fillStyle = mark.color
  if (mark.kind === 'text') {
    ctx.font = `${mark.size}px ${ANNOTATION_FONT}`
    ctx.textBaseline = 'top'
    mark.text.split('\n').forEach((line, index) => ctx.fillText(line, mark.x, mark.y + index * mark.size * TEXT_LINE_HEIGHT))
    return
  }
  ctx.lineWidth = mark.width
  if (mark.kind === 'pen') {
    const [first, ...rest] = mark.points
    if (!first) return
    ctx.beginPath()
    if (!rest.length) { ctx.arc(first.x, first.y, mark.width / 2, 0, Math.PI * 2); ctx.fill(); return }
    ctx.moveTo(first.x, first.y)
    for (const point of rest) ctx.lineTo(point.x, point.y)
    ctx.stroke()
    return
  }
  const left = Math.min(mark.x1, mark.x2), top = Math.min(mark.y1, mark.y2)
  const width = Math.abs(mark.x2 - mark.x1), height = Math.abs(mark.y2 - mark.y1)
  if (mark.kind === 'rect') { ctx.strokeRect(left, top, width, height); return }
  if (mark.kind === 'ellipse') {
    ctx.beginPath()
    ctx.ellipse(left + width / 2, top + height / 2, width / 2, height / 2, 0, 0, Math.PI * 2)
    ctx.stroke()
    return
  }
  const { shaftEnd, head } = arrowGeometry(mark)
  ctx.beginPath(); ctx.moveTo(mark.x1, mark.y1); ctx.lineTo(shaftEnd.x, shaftEnd.y); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(head[0].x, head[0].y); ctx.lineTo(head[1].x, head[1].y); ctx.lineTo(head[2].x, head[2].y); ctx.closePath(); ctx.fill()
}

/** Marks live in the displayed box's CSS pixels; the screenshot may be denser (Retina) or letterboxed. */
export function compositeScale(natural: { width: number; height: number }, box: { width: number; height: number }): number {
  if (box.width <= 0 || box.height <= 0) return 1
  return Math.min(natural.width / box.width, natural.height / box.height)
}

/** Largest box with the image's aspect ratio that fits the area, centered. */
export function fitContain(image: { width: number; height: number }, area: { width: number; height: number }): { left: number; top: number; width: number; height: number } {
  if (image.width <= 0 || image.height <= 0 || area.width <= 0 || area.height <= 0) return { left: 0, top: 0, width: 0, height: 0 }
  const scale = Math.min(area.width / image.width, area.height / image.height)
  const width = image.width * scale, height = image.height * scale
  return { left: (area.width - width) / 2, top: (area.height - height) / 2, width, height }
}

/** Draws the marks onto the screenshot at its native size and returns a PNG blob. */
export async function compositeAnnotation(backdrop: string, marks: readonly AnnotationMark[], box: { width: number; height: number }): Promise<Blob> {
  const image = new Image()
  image.src = backdrop
  await image.decode()
  const canvas = document.createElement('canvas')
  canvas.width = image.naturalWidth
  canvas.height = image.naturalHeight
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas unavailable.')
  ctx.drawImage(image, 0, 0)
  const scale = compositeScale({ width: image.naturalWidth, height: image.naturalHeight }, box)
  ctx.scale(scale, scale)
  for (const mark of marks) drawMark(ctx, mark)
  return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('PNG encoding failed.')), 'image/png'))
}

export const ANNOTATION_CONTEXT_OPEN = '<browser-annotation-context>'
export const ANNOTATION_CONTEXT_CLOSE = '</browser-annotation-context>'
/** Follows the file path in every note; restoreAnnotationContext reads the path back by it. */
const ANNOTATION_CONTEXT_SUBJECT = ' is a screenshot of the browser pane'
const escapeRegExp = (text: string): string => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Tells the model what the attached image is; stripped from titles and the timeline. */
export function annotationContextNote(fileName: string, annotated: boolean, pageUrl?: string): string {
  const what = annotated ? "with the user's annotations drawn on top" : 'as the user currently sees it, with no annotations'
  const page = pageUrl ? ` of ${pageUrl}` : ''
  return `${ANNOTATION_CONTEXT_OPEN}${fileName}${ANNOTATION_CONTEXT_SUBJECT}${page}, ${what}. Use the browser tools to inspect or interact with the live page.${ANNOTATION_CONTEXT_CLOSE}`
}

export function stripAnnotationContext(text: string): string {
  const pattern = new RegExp(`\\s*${ANNOTATION_CONTEXT_OPEN}[\\s\\S]*?${ANNOTATION_CONTEXT_CLOSE.replace('/', '\\/')}`, 'g')
  return text.replace(pattern, '')
}

/** Restore hidden screenshot notes only for attachments retained in an edited message. */
export function restoreAnnotationContext(original: string, edited: string): string {
  const pattern = new RegExp(`${escapeRegExp(ANNOTATION_CONTEXT_OPEN)}([\\s\\S]*?)${escapeRegExp(ANNOTATION_CONTEXT_CLOSE)}`, 'g')
  const notes = [...original.matchAll(pattern)]
    .filter((match) => {
      const pathEnd = match[1].indexOf(ANNOTATION_CONTEXT_SUBJECT)
      if (pathEnd <= 0) return false
      const mention = formatComposerPathMention(match[1].slice(0, pathEnd))
      return new RegExp(`(?:^|\\s)${escapeRegExp(mention)}(?=\\s|$)`).test(edited)
    })
    .map(match => match[0])
  return [edited, ...notes].join('\n')
}

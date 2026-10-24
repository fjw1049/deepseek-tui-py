import { describe, expect, it } from 'vitest'
import {
  EMPTY_ANNOTATION_HISTORY, annotationContextNote, arrowGeometry, commitMark, compositeScale, drawMark, fitContain,
  isMeaningfulMark, redoMark, restoreAnnotationContext, stripAnnotationContext, undoMark,
  type AnnotationContext, type AnnotationMark, type ShapeMark
} from './browser-annotation'

const rect = (x2: number, y2: number): ShapeMark => ({ kind: 'rect', x1: 0, y1: 0, x2, y2, color: '#E03131', width: 4 })

function recorder(): AnnotationContext & { calls: Array<[string, ...unknown[]]> } {
  const calls: Array<[string, ...unknown[]]> = []
  const record = (name: string) => (...args: unknown[]) => { calls.push([name, ...args]) }
  return {
    calls, lineCap: 'butt', lineJoin: 'miter', lineWidth: 1, strokeStyle: '', fillStyle: '', font: '', textBaseline: 'alphabetic',
    beginPath: record('beginPath'), moveTo: record('moveTo'), lineTo: record('lineTo'), stroke: record('stroke'),
    fill: record('fill'), arc: record('arc'), ellipse: record('ellipse'), strokeRect: record('strokeRect'),
    closePath: record('closePath'), fillText: record('fillText')
  } as AnnotationContext & { calls: Array<[string, ...unknown[]]> }
}

describe('annotation history', () => {
  it('undoes, redoes, and drops the redo stack on a new mark', () => {
    const a = rect(10, 10), b = rect(20, 20), c = rect(30, 30)
    let history = commitMark(commitMark(EMPTY_ANNOTATION_HISTORY, a), b)
    expect(history.present).toEqual([a, b])
    history = undoMark(history)
    expect(history.present).toEqual([a])
    expect(redoMark(history).present).toEqual([a, b])
    history = commitMark(history, c)
    expect(history.present).toEqual([a, c])
    expect(redoMark(history)).toBe(history)
    expect(undoMark(undoMark(undoMark(history))).present).toEqual([])
  })

  it('ignores stray clicks but keeps a single pen dot', () => {
    expect(isMeaningfulMark(rect(3, 40))).toBe(false)
    expect(isMeaningfulMark(rect(4, 4))).toBe(true)
    expect(isMeaningfulMark({ kind: 'arrow', x1: 0, y1: 0, x2: 3, y2: 0, color: '#000', width: 2 })).toBe(false)
    expect(isMeaningfulMark({ kind: 'text', x: 0, y: 0, text: '  \n', size: 18, color: '#000' })).toBe(false)
    expect(commitMark(EMPTY_ANNOTATION_HISTORY, rect(1, 1))).toBe(EMPTY_ANNOTATION_HISTORY)
    const dot: AnnotationMark = { kind: 'pen', points: [{ x: 5, y: 6 }], color: '#000', width: 8 }
    const ctx = recorder()
    drawMark(ctx, dot)
    expect(ctx.calls).toEqual([['beginPath'], ['arc', 5, 6, 4, 0, Math.PI * 2], ['fill']])
  })
})

describe('drawing', () => {
  it('normalizes shapes dragged up and to the left', () => {
    const ctx = recorder()
    drawMark(ctx, { kind: 'rect', x1: 50, y1: 40, x2: 10, y2: 20, color: '#1971C2', width: 2 })
    expect(ctx.calls).toEqual([['strokeRect', 10, 20, 40, 20]])
    expect(ctx.strokeStyle).toBe('#1971C2')
    const ellipse = recorder()
    drawMark(ellipse, { kind: 'ellipse', x1: 10, y1: 10, x2: 30, y2: 50, color: '#000', width: 2 })
    expect(ellipse.calls[1]).toEqual(['ellipse', 20, 30, 10, 20, 0, 0, Math.PI * 2])
  })

  it('points the arrow head at the end point', () => {
    const { shaftEnd, head } = arrowGeometry({ kind: 'arrow', x1: 0, y1: 0, x2: 100, y2: 0, color: '#000', width: 4 })
    expect(head[0]).toEqual({ x: 100, y: 0 })
    expect(head[1]).toEqual({ x: 84, y: -8 })
    expect(head[2]).toEqual({ x: 84, y: 8 })
    expect(shaftEnd.x).toBeCloseTo(88.8)
  })

  it('draws each text line below the previous one', () => {
    const ctx = recorder()
    drawMark(ctx, { kind: 'text', x: 10, y: 20, text: '第一行\n第二行', size: 20, color: '#000' })
    expect(ctx.calls).toEqual([['fillText', '第一行', 10, 20], ['fillText', '第二行', 10, 44]])
    expect(ctx.textBaseline).toBe('top')
  })
})

describe('compositing geometry', () => {
  it('maps CSS coordinates onto a 2x screenshot', () => {
    const scale = compositeScale({ width: 1600, height: 1000 }, { width: 800, height: 500 })
    expect(scale).toBe(2)
    expect({ x: 100 * scale, y: 50 * scale }).toEqual({ x: 200, y: 100 })
  })

  it('letterboxes a frame that does not match the area', () => {
    expect(fitContain({ width: 1200, height: 600 }, { width: 600, height: 600 })).toEqual({ left: 0, top: 150, width: 600, height: 300 })
    expect(fitContain({ width: 0, height: 600 }, { width: 600, height: 600 }).width).toBe(0)
  })
})

describe('context note', () => {
  it('names the file and page, and strips cleanly from display text', () => {
    const note = annotationContextNote('browser-annotation.png', true, 'https://www.baidu.com/')
    expect(note).toContain('browser-annotation.png is a screenshot of the browser pane of https://www.baidu.com/')
    expect(note).toContain("user's annotations")
    expect(stripAnnotationContext(`圈出来的这条是什么？\n\n${note}`)).toBe('圈出来的这条是什么？')
  })
})

it('restores only retained screenshot notes, including quoted paths and inline mentions', () => {
  const a = annotationContextNote('shots/first [1].png', true, 'https://example.test/a')
  const b = annotationContextNote('shots/second.png', false, 'https://example.test/b')
  const original = `@"shots/first [1].png"\n@shots/second.png\nCompare\n${a}\n${b}`
  const edited = 'Explain @"shots/first [1].png" please'
  expect(restoreAnnotationContext(original, edited)).toBe(`${edited}\n${a}`)
  expect(restoreAnnotationContext(original, '@shots/second.png.bak')).toBe('@shots/second.png.bak')
  expect(restoreAnnotationContext(original, 'No screenshots')).toBe('No screenshots')
})

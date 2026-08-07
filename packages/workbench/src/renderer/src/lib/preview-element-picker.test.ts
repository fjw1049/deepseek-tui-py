import { describe, expect, it } from 'vitest'
import {
  PREVIEW_PICK_CONSOLE_PREFIX,
  extractWebviewConsoleMessage,
  parsePreviewPickConsoleMessage,
  type PreviewElementPick
} from './preview-element-picker'
import {
  formatPreviewPickChipLabel,
  formatPreviewPickJson,
  formatPreviewPickWireMessage,
  formatPreviewPicksJson,
  parsePreviewPickWireMessage,
  upsertPreviewPick,
  PREVIEW_PICK_MAX,
  PREVIEW_PICK_WIRE_MARKER
} from './preview-pick-message'

describe('parsePreviewPickConsoleMessage', () => {
  it('parses a pick payload', () => {
    const wire = {
      type: 'pick',
      payload: {
        selector: 'section.hero > h1',
        tagName: 'H1',
        id: 'title',
        classes: ['title', 'xl'],
        textPreview: 'Hello',
        htmlSnippet: '<h1 id="title" class="title xl">Hello</h1>',
        ancestry: ['main', 'section.hero', 'h1#title']
      }
    }
    const parsed = parsePreviewPickConsoleMessage(
      `${PREVIEW_PICK_CONSOLE_PREFIX}${JSON.stringify(wire)}`
    )
    expect(parsed).toEqual({
      type: 'pick',
      payload: {
        selector: 'section.hero > h1',
        tagName: 'h1',
        id: 'title',
        classes: ['title', 'xl'],
        textPreview: 'Hello',
        htmlSnippet: '<h1 id="title" class="title xl">Hello</h1>',
        ancestry: ['main', 'section.hero', 'h1#title']
      }
    })
  })

  it('parses cancel', () => {
    expect(
      parsePreviewPickConsoleMessage(`${PREVIEW_PICK_CONSOLE_PREFIX}{"type":"cancel"}`)
    ).toEqual({ type: 'cancel' })
  })

  it('ignores unrelated console noise', () => {
    expect(parsePreviewPickConsoleMessage('hello')).toBeNull()
    expect(parsePreviewPickConsoleMessage(`${PREVIEW_PICK_CONSOLE_PREFIX}{not-json`)).toBeNull()
    expect(
      parsePreviewPickConsoleMessage(`${PREVIEW_PICK_CONSOLE_PREFIX}{"type":"pick","payload":{}}`)
    ).toBeNull()
  })

  it('truncates oversized fields', () => {
    const huge = 'x'.repeat(5000)
    const parsed = parsePreviewPickConsoleMessage(
      `${PREVIEW_PICK_CONSOLE_PREFIX}${JSON.stringify({
        type: 'pick',
        payload: {
          selector: 'div',
          tagName: 'div',
          classes: [],
          textPreview: huge,
          htmlSnippet: huge,
          ancestry: ['a', 'b', 'c', 'd', 'e']
        }
      })}`
    )
    expect(parsed?.type).toBe('pick')
    if (parsed?.type !== 'pick') return
    expect(parsed.payload.textPreview.length).toBe(200)
    expect(parsed.payload.htmlSnippet.length).toBe(1200)
    expect(parsed.payload.ancestry).toHaveLength(3)
  })
})

describe('extractWebviewConsoleMessage', () => {
  it('reads event.message (Electron webview console-message shape)', () => {
    const event = new Event('console-message') as Event & { message?: string }
    event.message = `${PREVIEW_PICK_CONSOLE_PREFIX}{"type":"cancel"}`
    expect(extractWebviewConsoleMessage(event)).toBe(event.message)
  })

  it('returns null when message is missing', () => {
    expect(extractWebviewConsoleMessage(new Event('console-message'))).toBeNull()
  })
})

describe('upsertPreviewPick', () => {
  const a: PreviewElementPick = {
    filePath: 'docs/a.html',
    selector: 'h1',
    tagName: 'h1',
    classes: [],
    textPreview: 'A',
    htmlSnippet: '<h1>A</h1>',
    ancestry: []
  }
  const b: PreviewElementPick = {
    ...a,
    selector: 'h2',
    tagName: 'h2',
    textPreview: 'B',
    htmlSnippet: '<h2>B</h2>'
  }

  it('appends a new pick', () => {
    expect(upsertPreviewPick([], a)).toEqual({ kind: 'added', picks: [a] })
    expect(upsertPreviewPick([a], b)).toEqual({ kind: 'added', picks: [a, b] })
  })

  it('toggles off an existing filePath+selector', () => {
    expect(upsertPreviewPick([a, b], a)).toEqual({ kind: 'removed', picks: [b] })
  })

  it('treats same selector with different html as distinct picks', () => {
    // Class-less static elements collapse to identical truncated selectors;
    // the snippet must keep them from toggling each other off.
    const collapsed1: PreviewElementPick = {
      filePath: 'docs/a.html',
      selector: 'div > div > p',
      tagName: 'p',
      classes: [],
      textPreview: 'First',
      htmlSnippet: '<p>First</p>',
      ancestry: []
    }
    const collapsed2: PreviewElementPick = {
      ...collapsed1,
      textPreview: 'Second',
      htmlSnippet: '<p>Second</p>'
    }
    expect(upsertPreviewPick([collapsed1], collapsed2)).toEqual({
      kind: 'added',
      picks: [collapsed1, collapsed2]
    })
    // Exact same node (same snippet) still toggles off.
    expect(upsertPreviewPick([collapsed1, collapsed2], collapsed1)).toEqual({
      kind: 'removed',
      picks: [collapsed2]
    })
  })

  it('signals limit without mutating when full', () => {
    const full = Array.from({ length: PREVIEW_PICK_MAX }, (_, i) => ({
      ...a,
      selector: `el-${i}`
    }))
    const next = { ...a, selector: 'overflow' }
    expect(upsertPreviewPick(full, next)).toEqual({ kind: 'limit', picks: full })
  })
})

describe('preview pick composer helpers', () => {
  const samplePick: PreviewElementPick = {
    filePath: 'docs/demo.html',
    selector: 'h1.title',
    tagName: 'h1',
    classes: ['title'],
    textPreview: 'Hello',
    htmlSnippet: '<h1 class="title">Hello</h1>',
    ancestry: ['main', 'h1.title']
  }
  const secondPick: PreviewElementPick = {
    filePath: 'docs/demo.html',
    selector: 'p.lead',
    tagName: 'p',
    classes: ['lead'],
    textPreview: 'Lead',
    htmlSnippet: '<p class="lead">Lead</p>',
    ancestry: ['main', 'p.lead']
  }

  it('builds a short chip label', () => {
    expect(formatPreviewPickChipLabel(samplePick)).toBe('demo.html · h1.title')
  })

  it('builds compact JSON for the wire payload', () => {
    const json = formatPreviewPickJson(samplePick)
    expect(JSON.parse(json)).toMatchObject({
      filePath: 'docs/demo.html',
      selector: 'h1.title',
      htmlSnippet: '<h1 class="title">Hello</h1>'
    })
  })

  it('round-trips multi-pick wire message to short UI chips', () => {
    const wire = formatPreviewPickWireMessage([samplePick, secondPick], '标题改短一点')
    expect(wire.startsWith(PREVIEW_PICK_WIRE_MARKER)).toBe(true)
    expect(JSON.parse(formatPreviewPicksJson([samplePick, secondPick]))).toHaveLength(2)
    const parsed = parsePreviewPickWireMessage(wire)
    expect(parsed).toMatchObject({
      userRequest: '标题改短一点',
      chipLabels: ['demo.html · h1.title', 'demo.html · p.lead'],
      picks: [
        {
          filePath: 'docs/demo.html',
          selector: 'h1.title',
          htmlSnippet: '<h1 class="title">Hello</h1>'
        },
        {
          filePath: 'docs/demo.html',
          selector: 'p.lead',
          htmlSnippet: '<p class="lead">Lead</p>'
        }
      ]
    })
  })

  it('accepts a single pick argument and still emits a JSON array', () => {
    const wire = formatPreviewPickWireMessage(samplePick, '改一下')
    const parsed = parsePreviewPickWireMessage(wire)
    expect(parsed?.picks).toHaveLength(1)
    const raw = JSON.parse(/```json\s*\n([\s\S]*?)\n```/.exec(wire)?.[1] ?? 'null')
    expect(Array.isArray(raw)).toBe(true)
    expect(raw).toEqual(
      expect.arrayContaining([expect.objectContaining({ selector: 'h1.title' })])
    )
  })

  it('parses the legacy unmarked single-object wire form', () => {
    const legacy = [
      '请修改预览中选中的模块（先用 htmlSnippet 在文件里做唯一匹配；匹配不到再用 selector；不要整页重写）。',
      '```json',
      formatPreviewPickJson(samplePick),
      '```',
      '',
      '用户要求：',
      '把间距加大'
    ].join('\n')
    const parsed = parsePreviewPickWireMessage(legacy)
    expect(parsed?.userRequest).toBe('把间距加大')
    expect(parsed?.chipLabels).toEqual(['demo.html · h1.title'])
    expect(parsed?.picks).toHaveLength(1)
  })
})

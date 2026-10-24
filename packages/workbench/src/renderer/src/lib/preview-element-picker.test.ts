import { describe, expect, it, vi } from 'vitest'
import { Window } from 'happy-dom'
import {
  PREVIEW_PICK_CONSOLE_PREFIX,
  buildPreviewPickerCleanupScript,
  buildPreviewPickerInjectScript,
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
    const huge = 'x'.repeat(3000)
    const parsed = parsePreviewPickConsoleMessage(
      `${PREVIEW_PICK_CONSOLE_PREFIX}${JSON.stringify({
        type: 'pick',
        payload: {
          selector: 'div',
          tagName: 'div',
          classes: [huge],
          textPreview: huge,
          htmlSnippet: huge,
          ancestry: [huge, 'b', 'c', 'd', 'e']
        }
      })}`
    )
    expect(parsed?.type).toBe('pick')
    if (parsed?.type !== 'pick') return
    expect(parsed.payload.textPreview.length).toBe(200)
    expect(parsed.payload.htmlSnippet.length).toBe(2000)
    expect(parsed.payload.ancestry).toHaveLength(4)
    expect(parsed.payload.classes[0]).toHaveLength(128)
    expect(parsed.payload.ancestry[0]).toHaveLength(500)
  })

  it('rejects oversized console messages before parsing JSON', () => {
    expect(parsePreviewPickConsoleMessage(`${PREVIEW_PICK_CONSOLE_PREFIX}${'x'.repeat(40_000)}`)).toBeNull()
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

describe('preview picker arm/disarm scripts', () => {
  it('restores the page cursor when Inspect is disabled', () => {
    const guest = new Window()
    guest.document.documentElement.style.cursor = 'pointer'
    new Function('window', 'document', buildPreviewPickerInjectScript())(guest, guest.document)
    expect(guest.document.documentElement.style.cursor).toBe('crosshair')
    new Function('window', 'document', buildPreviewPickerCleanupScript())(guest, guest.document)
    expect(guest.document.documentElement.style.cursor).toBe('pointer')
    expect(guest.document.getElementById('__ds_preview_pick_overlay__')).toBeNull()
  })
  it('cleanup clears the arm flag before dispose so orphaned listeners no-op', () => {
    const cleanup = buildPreviewPickerCleanupScript()
    const armIdx = cleanup.indexOf('__dsPreviewPickActive = false')
    const disposeIdx = cleanup.indexOf('__dsPreviewPick?.dispose')
    expect(armIdx).toBeGreaterThanOrEqual(0)
    expect(disposeIdx).toBeGreaterThan(armIdx)
  })

  it('reports attributes, box and siblings for the picked element', () => {
    const guest = new Window()
    guest.document.body.innerHTML = '<nav><a id="go" class="link primary main" href="/next" aria-label="Next page">Two</a><span class="sep"></span></nav>'
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    try {
      new Function('window', 'document', buildPreviewPickerInjectScript())(guest, guest.document)
      guest.document.getElementById('go')!.dispatchEvent(new guest.MouseEvent('click', { bubbles: true }))
      const parsed = parsePreviewPickConsoleMessage(String(warn.mock.calls.at(-1)?.[0]))
      expect(parsed?.type).toBe('pick')
      if (parsed?.type !== 'pick') return
      expect(parsed.payload.attributes).toEqual({ 'aria-label': 'Next page', href: '/next' })
      expect(parsed.payload.rect).toEqual({ x: 0, y: 0, width: 0, height: 0 })
      expect(parsed.payload.siblingHtml).toBe('<!-- SELECTED --><a id="go" class="link primary main" />\n<span class="sep" />')
    } finally {
      warn.mockRestore()
      new Function('window', 'document', buildPreviewPickerCleanupScript())(guest, guest.document)
    }
  })

  it('keeps presses from the page while armed so picking never selects text, and lets them through after', () => {
    const guest = new Window()
    guest.document.body.innerHTML = '<p id="t">Selectable</p>'
    const target = guest.document.getElementById('t')!
    const press = (): boolean => !target.dispatchEvent(new guest.MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 }))
    new Function('window', 'document', buildPreviewPickerInjectScript())(guest, guest.document)
    expect(press()).toBe(true)
    new Function('window', 'document', buildPreviewPickerCleanupScript())(guest, guest.document)
    expect(press()).toBe(false)
  })

  it('drops malformed optional fields instead of the whole pick', () => {
    const parsed = parsePreviewPickConsoleMessage(`${PREVIEW_PICK_CONSOLE_PREFIX}${JSON.stringify({
      type: 'pick',
      payload: { selector: 'p', tagName: 'p', classes: [], textPreview: '', htmlSnippet: '<p></p>', ancestry: [],
        styles: { color: 'red', bad: 3 }, rect: { x: 1, y: 'no', width: 2, height: 3 }, attributes: [] }
    })}`)
    expect(parsed?.type === 'pick' && parsed.payload).toMatchObject({ styles: { color: 'red' } })
    expect(parsed?.type === 'pick' && 'rect' in parsed.payload).toBe(false)
    expect(parsed?.type === 'pick' && 'attributes' in parsed.payload).toBe(false)
  })

  it('inject gates click/move handlers on the arm flag', () => {
    const inject = buildPreviewPickerInjectScript()
    expect(inject).toContain('__dsPreviewPickActive = true')
    expect(inject).toContain('isArmed()')
    expect(inject).toMatch(/onClick[\s\S]*if \(!isArmed\(\)\) return/)
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

  it('preserves request text that contains the wire request marker', () => {
    const request = '增加说明“用户要求：请先登录”，并调整样式'
    const parsed = parsePreviewPickWireMessage(formatPreviewPickWireMessage(samplePick, request))
    expect(parsed?.userRequest).toBe(request)
  })

  it('round-trips a web page pick with its URL and extra context', () => {
    const pagePick: PreviewElementPick = {
      ...samplePick, filePath: '', pageUrl: 'https://www.baidu.com/s?wd=1',
      styles: { color: 'rgb(0, 0, 0)' }, rect: { x: 10, y: 20, width: 300, height: 36 },
      attributes: { href: '/next' }, siblingHtml: '<!-- SELECTED --><h1 class="title" />'
    }
    const wire = formatPreviewPickWireMessage(pagePick, '这条新闻讲的是什么')
    expect(wire).toContain('带 pageUrl 的是网页上的元素')
    const raw = JSON.parse(/```json\s*\n([\s\S]*?)\n```/.exec(wire)?.[1] ?? 'null')
    expect(raw[0]).not.toHaveProperty('filePath')
    expect(raw[0]).toMatchObject({ pageUrl: 'https://www.baidu.com/s?wd=1', rect: { width: 300 }, attributes: { href: '/next' } })
    const parsed = parsePreviewPickWireMessage(wire)
    expect(parsed?.userRequest).toBe('这条新闻讲的是什么')
    expect(parsed?.chipLabels).toEqual(['www.baidu.com · h1.title'])
    expect(parsed?.picks[0]).toMatchObject({ filePath: '', pageUrl: 'https://www.baidu.com/s?wd=1' })
  })

  it('keeps the file intro when every pick comes from a workspace file', () => {
    expect(formatPreviewPickWireMessage([samplePick, secondPick], 'x')).toContain('请修改以下预览选中模块')
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

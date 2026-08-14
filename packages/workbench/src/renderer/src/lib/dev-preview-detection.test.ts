import { describe, expect, it } from 'vitest'
import type { ChatBlock } from '../agent/types'
import { extractLatestTurnDevPreviewUrls } from './dev-preview-detection'

describe('extractLatestTurnDevPreviewUrls', () => {
  it('does not treat a localhost mention plus 打开/运行 as a preview', () => {
    const blocks: ChatBlock[] = [
      { kind: 'user', id: 'u1', text: 'review this' },
      {
        kind: 'assistant',
        id: 'a1',
        text:
          'fetch_url 会跟着跳转到 http://localhost:8080/ 和 http://[::1]/。' +
          '运行检查后再打开结果。'
      }
    ]
    expect(extractLatestTurnDevPreviewUrls(blocks)).toEqual([])
  })

  it('still picks a vite-style preview from assistant text', () => {
    const blocks: ChatBlock[] = [
      { kind: 'user', id: 'u1', text: 'start the frontend' },
      {
        kind: 'assistant',
        id: 'a1',
        text: 'Vite dev server ready.\nLocal: http://localhost:5173/'
      }
    ]
    expect(extractLatestTurnDevPreviewUrls(blocks)).toEqual(['http://localhost:5173/'])
  })

  it('picks a URL when the assistant explicitly talks about 预览', () => {
    const blocks: ChatBlock[] = [
      { kind: 'user', id: 'u1', text: 'show the page' },
      {
        kind: 'assistant',
        id: 'a1',
        text: '预览已就绪：http://127.0.0.1:3000/'
      }
    ]
    expect(extractLatestTurnDevPreviewUrls(blocks)).toEqual(['http://127.0.0.1:3000/'])
  })

  it('does not treat bare 127.0.0.1 / localhost as a preview', () => {
    const blocks: ChatBlock[] = [
      { kind: 'user', id: 'u1', text: 'review ssrf' },
      {
        kind: 'assistant',
        id: 'a1',
        text: 'fetch_url 不得访问浏览器里的 127.0.0.1 和 localhost，避免打到本机服务。'
      }
    ]
    expect(extractLatestTurnDevPreviewUrls(blocks)).toEqual([])
  })
})

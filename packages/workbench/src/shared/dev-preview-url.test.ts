import { describe, expect, it } from 'vitest'
import {
  isBrowsableUrl,
  isLocalPreviewUrl,
  normalizeBrowseUrlInput,
  normalizeDevPreviewUrlInput
} from './dev-preview-url'

describe('normalizeDevPreviewUrlInput / isLocalPreviewUrl', () => {
  it('accepts localhost and loopback', () => {
    expect(normalizeDevPreviewUrlInput('http://127.0.0.1:5173')).toBe('http://127.0.0.1:5173/')
    expect(normalizeDevPreviewUrlInput('localhost:3000')).toBe('http://localhost:3000/')
    expect(isLocalPreviewUrl('http://192.168.1.10:8080/app')).toBe(true)
  })

  it('maps port-only input to loopback', () => {
    expect(normalizeDevPreviewUrlInput('5173')).toBe('http://127.0.0.1:5173/')
  })

  it('rejects public hosts', () => {
    expect(normalizeDevPreviewUrlInput('https://www.baidu.com')).toBeNull()
    expect(normalizeDevPreviewUrlInput('https://www.bilibili.com')).toBeNull()
    expect(isLocalPreviewUrl('https://example.com')).toBe(false)
  })
})

describe('normalizeBrowseUrlInput / isBrowsableUrl', () => {
  it('still accepts local preview URLs', () => {
    expect(normalizeBrowseUrlInput('5173')).toBe('http://127.0.0.1:5173/')
    expect(normalizeBrowseUrlInput('http://127.0.0.1:5173/demo')).toBe(
      'http://127.0.0.1:5173/demo'
    )
  })

  it('accepts public https URLs', () => {
    expect(normalizeBrowseUrlInput('https://www.baidu.com')).toBe('https://www.baidu.com/')
    expect(normalizeBrowseUrlInput('https://www.bilibili.com/')).toBe('https://www.bilibili.com/')
    expect(isBrowsableUrl('https://example.com/path')).toBe(true)
  })

  it('defaults bare public hosts to https', () => {
    expect(normalizeBrowseUrlInput('www.baidu.com')).toBe('https://www.baidu.com/')
    expect(normalizeBrowseUrlInput('bilibili.com/video/123')).toBe(
      'https://bilibili.com/video/123'
    )
  })

  it('rejects public http and non-http(s) schemes', () => {
    expect(normalizeBrowseUrlInput('http://www.baidu.com')).toBeNull()
    expect(normalizeBrowseUrlInput('file:///tmp/x.html')).toBeNull()
    expect(normalizeBrowseUrlInput('javascript:alert(1)')).toBeNull()
    expect(isBrowsableUrl('http://example.com')).toBe(false)
  })
})

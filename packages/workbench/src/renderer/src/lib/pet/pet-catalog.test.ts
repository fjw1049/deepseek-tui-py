// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest'
import { resolvePetSpritesheetSrc } from './pet-catalog'

afterEach(() => vi.restoreAllMocks())

it('rejects undecodable sprites and revokes the failed blob before it reaches the UI', async () => {
  const decode = vi.spyOn(Image.prototype, 'decode').mockRejectedValue(new Error('invalid image'))
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:invalid')
  const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  Object.defineProperty(window, 'dsGui', { configurable: true, value: {
    resolvePetSpritesheet: vi.fn().mockResolvedValue({ ok: true, slug: 'boba', mime: 'image/webp', base64: btoa('invalid') })
  } })
  await expect(resolvePetSpritesheetSrc('boba')).rejects.toThrow('invalid image')
  expect(decode).toHaveBeenCalledOnce()
  expect(revoke).toHaveBeenCalledWith('blob:invalid')
})

it('keeps a decoded sprite alive until the consumer releases it', async () => {
  vi.spyOn(Image.prototype, 'decode').mockResolvedValue(undefined)
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:valid')
  const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  Object.defineProperty(window, 'dsGui', { configurable: true, value: {
    resolvePetSpritesheet: vi.fn().mockResolvedValue({ ok: true, slug: 'boba', mime: 'image/webp', base64: btoa('valid') })
  } })
  const result = await resolvePetSpritesheetSrc('boba')
  expect(result.src).toBe('blob:valid')
  expect(revoke).not.toHaveBeenCalled()
  result.revoke()
  expect(revoke).toHaveBeenCalledWith('blob:valid')
})

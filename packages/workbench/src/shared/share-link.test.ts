import { expect, it } from 'vitest'
import { parseSharedConversationLink } from './share-link'
const url = `https://shares.example.com/s/${'a'.repeat(43)}`
it('decodes only a valid shared conversation URL', () => {
  expect(parseSharedConversationLink(`deepseek-gui://share?url=${encodeURIComponent(url)}`)).toBe(url)
})
it.each(['javascript:alert(1)', 'file:///etc/passwd', 'http://private.example/s/' + 'a'.repeat(43), url + '?key=secret', 'https://user:pass@shares.example.com/s/' + 'a'.repeat(43)])('rejects unsupported link %s', value => {
  expect(parseSharedConversationLink(`deepseek-gui://share?url=${encodeURIComponent(value)}`)).toBeNull()
})
it('does not accept commands or other routes', () => {
  expect(parseSharedConversationLink(`deepseek-gui://execute?url=${encodeURIComponent(url)}`)).toBeNull()
})

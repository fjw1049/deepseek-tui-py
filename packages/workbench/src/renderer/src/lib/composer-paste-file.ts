/** Keep in sync with ``src/deepseek_tui/state/paste_file.py``. */
export const LARGE_PASTE_MIN_LINES = 8
export const LARGE_PASTE_MIN_CHARS = 800

export function isLargePaste(text: string): boolean {
  if (!text.trim()) return false
  if (text.length >= LARGE_PASTE_MIN_CHARS) return true
  return text.split(/\r\n|\n|\r/).length >= LARGE_PASTE_MIN_LINES
}

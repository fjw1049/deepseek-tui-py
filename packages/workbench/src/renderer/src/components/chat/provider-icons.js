import claudeSvg from '../../assets/provider-icons/claude.svg?raw'
import openaiSvg from '../../assets/provider-icons/openai.svg?raw'
import geminiSvg from '../../assets/provider-icons/gemini.svg?raw'
import grokSvg from '../../assets/provider-icons/grok.svg?raw'
import deepseekSvg from '../../assets/provider-icons/deepseek.svg?raw'
import glmSvg from '../../assets/provider-icons/glm.svg?raw'
import kimiSvg from '../../assets/provider-icons/kimi.svg?raw'
import qwenSvg from '../../assets/provider-icons/qwen.svg?raw'
import minimaxSvg from '../../assets/provider-icons/minimax.svg?raw'

/** @typedef {{ key: string, color: string, svg: string, colored?: boolean }} ProviderIcon */

/** @type {Record<string, ProviderIcon>} */
const ICONS = {
  claude: { key: 'claude', color: '#D97757', svg: claudeSvg },
  openai: { key: 'openai', color: '#10A37F', svg: openaiSvg },
  codex: { key: 'codex', color: '#10A37F', svg: openaiSvg },
  gemini: { key: 'gemini', color: '#8E75B2', svg: geminiSvg },
  grok: { key: 'grok', color: 'var(--ds-text, #1A1A1A)', svg: grokSvg },
  deepseek: { key: 'deepseek', color: '#4D6BFE', svg: deepseekSvg },
  // ChatGLM bubble mark — readable at 12px. The old Zhipu constellation
  // glyph collapses into a scribble that looks like a stray "Z".
  glm: { key: 'glm', color: '#3859FF', svg: glmSvg },
  kimi: { key: 'kimi', color: '#027AFF', svg: kimiSvg, colored: true },
  qwen: { key: 'qwen', color: '#615CED', svg: qwenSvg, colored: true },
  minimax: { key: 'minimax', color: '#E2167E', svg: minimaxSvg, colored: true },
}

let iconUid = 0

/**
 * Make gradient / paint-server ids unique so multiple icons in one shadow tree
 * do not collide (qwen/minimax color SVGs use url(#…)).
 * @param {string} svg
 */
export function uniquifySvgIds(svg) {
  const uid = `p${++iconUid}`
  return String(svg || '')
    .replace(/\bid="([^"]+)"/g, (_m, id) => `id="${id}-${uid}"`)
    .replace(/url\(#([^)]+)\)/g, (_m, id) => `url(#${id}-${uid})`)
}

/**
 * Brand matching must use the *model* id/label, never the custom-endpoint
 * provider slug alone. Endpoint ids like `hs` / `qingyun` host many vendors;
 * treating `provider === 'hs'` as GLM made every hs/* model share one icon.
 *
 * @param {{ providerId?: string, id?: string, label?: string }} parts
 * @returns {ProviderIcon}
 */
export function resolveProviderIcon(parts = {}) {
  const wireId = String(parts.id || '')
  const modelPart = wireId.includes('::') ? wireId.slice(wireId.indexOf('::') + 2) : wireId
  // Prefer the segment after "/" in labels like "hs/glm-5.2".
  const label = String(parts.label || '')
  const labelModel = label.includes('/') ? label.slice(label.lastIndexOf('/') + 1) : label
  const hay = [modelPart, labelModel, wireId, label]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()

  if (/(claude|anthropic)/.test(hay)) return ICONS.claude
  if (/(codex|openai|\bgpt[-_.\d]|o[1-4][-_.]|\bchatgpt\b)/.test(hay)) return ICONS.codex
  if (/(gemini|google)/.test(hay)) return ICONS.gemini
  if (/(grok|\bxai\b)/.test(hay)) return ICONS.grok
  if (/(deepseek)/.test(hay)) return ICONS.deepseek
  if (/(glm|zhipu|chatglm|\bzai\b|\bz\.ai\b|智谱|清言)/.test(hay)) return ICONS.glm
  if (/(kimi|moonshot|月之暗面|moonshotai)/.test(hay)) return ICONS.kimi
  if (/(qwen|qwq|通义|千问|dashscope)/.test(hay)) return ICONS.qwen
  if (/(minimax|海螺|\babab[-_.]|minimaxi)/.test(hay)) return ICONS.minimax

  // Built-in DeepSeek models have no vendor keyword beyond the wire id prefix.
  const provider = String(parts.providerId || '').toLowerCase()
  if (!hay || provider === 'deepseek' || modelPart.startsWith('deepseek')) {
    return ICONS.deepseek
  }

  return {
    key: 'unknown',
    color: '#64748B',
    svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="9"/></svg>`,
  }
}

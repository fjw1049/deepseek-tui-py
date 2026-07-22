import claudeSvg from '../../assets/provider-icons/claude.svg?raw'
import openaiSvg from '../../assets/provider-icons/openai.svg?raw'
import geminiSvg from '../../assets/provider-icons/gemini.svg?raw'
import grokSvg from '../../assets/provider-icons/grok.svg?raw'
import deepseekSvg from '../../assets/provider-icons/deepseek.svg?raw'
import glmSvg from '../../assets/provider-icons/glm.svg?raw'
import kimiSvg from '../../assets/provider-icons/kimi.svg?raw'
import qwenSvg from '../../assets/provider-icons/qwen.svg?raw'
import minimaxSvg from '../../assets/provider-icons/minimax.svg?raw'
import doubaoPng from '../../assets/provider-icons/doubao.png'
import { resolveProviderIconBrand } from './provider-icon-match'

/** @typedef {{ key: string, color: string, svg: string, colored?: boolean }} ProviderIcon */

function photoIconSvg(src) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"><defs><clipPath id="clip"><circle cx="12" cy="12" r="12"/></clipPath></defs><image href="${src}" width="24" height="24" preserveAspectRatio="xMidYMid slice" clip-path="url(#clip)"/></svg>`
}

/** @type {Record<string, ProviderIcon>} */
const ICONS = {
  claude: { key: 'claude', color: '#D97757', svg: claudeSvg },
  openai: { key: 'openai', color: '#10A37F', svg: openaiSvg },
  codex: { key: 'codex', color: '#10A37F', svg: openaiSvg },
  gemini: { key: 'gemini', color: '#8E75B2', svg: geminiSvg },
  grok: { key: 'grok', color: 'var(--ds-text, #1A1A1A)', svg: grokSvg },
  deepseek: { key: 'deepseek', color: '#4D6BFE', svg: deepseekSvg },
  // Official Z.ai glyph (international brand for Zhipu / GLM).
  glm: { key: 'glm', color: '#1F63EC', svg: glmSvg },
  kimi: { key: 'kimi', color: '#027AFF', svg: kimiSvg, colored: true },
  qwen: { key: 'qwen', color: '#615CED', svg: qwenSvg, colored: true },
  minimax: { key: 'minimax', color: '#E2167E', svg: minimaxSvg, colored: true },
  // Doubao app icon — short-haired girl avatar (not the abstract ring mark).
  doubao: {
    key: 'doubao',
    color: '#7EB8F7',
    svg: photoIconSvg(doubaoPng),
    colored: true
  },
}

const UNKNOWN_ICON = {
  key: 'unknown',
  color: '#64748B',
  svg: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="9"/></svg>`,
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

export { modelIconMatchText, resolveProviderIconBrand } from './provider-icon-match'

/**
 * Brand matching must use the *model* id/label, never the custom-endpoint
 * provider slug or display name. Endpoint ids/names like `hs` / `zhipu` /
 * `qingyun` host many vendors.
 *
 * @param {{ providerId?: string, id?: string, label?: string }} parts
 * @returns {ProviderIcon}
 */
export function resolveProviderIcon(parts = {}) {
  const brand = resolveProviderIconBrand(parts)
  return ICONS[brand] || UNKNOWN_ICON
}

import type { ReactElement } from 'react'
import claudeSvg from '../../assets/provider-icons/claude.svg?raw'
import codebuddySvg from '../../assets/provider-icons/codebuddy.svg?raw'
import cursorSvg from '../../assets/provider-icons/cursor.svg?raw'
import geminiColorSvg from '../../assets/provider-icons/gemini-color.svg?raw'
import openaiSvg from '../../assets/provider-icons/openai.svg?raw'
import ownGridSvg from '../../assets/provider-icons/own-grid.svg?raw'
import qwenSvg from '../../assets/provider-icons/qwen.svg?raw'
import { skillSourceFromPath, skillSourceIconKey } from '@shared/skill-source'
import { uniquifySvgIds } from '../chat/provider-icons.js'

type Props = {
  path: string
  size?: number
}

type SkillBrandTile = {
  svg: string
  colored?: boolean
}

const TILES: Record<string, SkillBrandTile> = {
  claude: { svg: claudeSvg },
  codex: { svg: openaiSvg },
  cursor: { svg: cursorSvg },
  gemini: { svg: geminiColorSvg, colored: true },
  qwen: { svg: qwenSvg, colored: true },
  codebuddy: { svg: codebuddySvg },
  own: { svg: ownGridSvg }
}

export function SkillSourceIcon({ path, size = 40 }: Props): ReactElement {
  const brand = skillSourceIconKey(skillSourceFromPath(path))
  const tile = TILES[brand] ?? TILES.own
  const classes = ['ds-skill-brand', tile.colored ? 'is-colored' : ''].filter(Boolean).join(' ')

  return (
    <span
      className={classes}
      data-brand={brand}
      style={{ width: size, height: size }}
      aria-hidden
      dangerouslySetInnerHTML={{ __html: uniquifySvgIds(tile.svg) }}
    />
  )
}

export function skillSourceTileSize(count: number): number {
  if (count <= 1) return 40
  if (count === 2) return 28
  if (count <= 4) return 26
  return 20
}

export function SkillSourceStack({ paths }: { paths: readonly string[] }): ReactElement {
  const shown = paths.slice(0, 6)
  return (
    <span className="ds-skill-source-stack" data-count={shown.length}>
      {shown.map((filePath, index) => (
        <span key={`${filePath}:${index}`} className="ds-skill-source-stack__tile">
          <SkillSourceIcon path={filePath} size={skillSourceTileSize(shown.length)} />
        </span>
      ))}
    </span>
  )
}

import type { CSSProperties, ReactElement } from 'react'
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

export function SkillSourceStack({ paths, labelFor }: {
  paths: readonly string[]
  /** Names each icon's source on hover; the row already lists them as text. */
  labelFor?: (path: string) => string
}): ReactElement {
  const count = paths.length
  const size = count <= 1 ? 40 : 32
  const halfAngle = Math.min(18, Math.max(0, count - 1) * 5)
  return (
    <span
      className="ds-skill-source-stack"
      data-count={count}
      style={{
        '--source-count': count,
        '--source-half-angle': `${halfAngle}deg`,
        '--source-spread': `${size + 128 * Math.sin(halfAngle * Math.PI / 180)}px`,
        '--source-size': `${size}px`
      } as CSSProperties}
      aria-hidden
      title=""
    >
      {paths.map((filePath, index) => (
        <span
          key={`${filePath}:${index}`}
          className="ds-skill-source-stack__tile"
          title={labelFor?.(filePath)}
          style={{
            '--source-index': index,
            '--source-angle': `${count <= 1 ? 0 : -halfAngle + index * 2 * halfAngle / (count - 1)}deg`
          } as CSSProperties}
        >
          <SkillSourceIcon path={filePath} size={size} />
        </span>
      ))}
    </span>
  )
}

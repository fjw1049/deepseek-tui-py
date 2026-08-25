import type { ReactElement } from 'react'
import { File } from 'lucide-react'
import { materialIconSvgByName } from 'virtual:material-icons'
import { materialIconNameForPath, type MaterialIconOptions } from '../../lib/file-icon'

function materialIconDataUri(name: string): string | null {
  const closed = name.endsWith('-open') ? name.slice(0, -5) : null
  const svg =
    materialIconSvgByName[name] ??
    (closed ? materialIconSvgByName[closed] : undefined) ??
    materialIconSvgByName.file
  if (!svg) return null
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`
}

export function FileKindIcon({
  path,
  className,
  directory,
  expanded
}: {
  path: string
  className?: string
} & MaterialIconOptions): ReactElement {
  const src = materialIconDataUri(materialIconNameForPath(path, { directory, expanded }))
  return (
    <span className={['ds-file-kind-icon', className].filter(Boolean).join(' ')} aria-hidden>
      {src ? (
        <img src={src} alt="" draggable={false} />
      ) : (
        <File className="ds-file-kind-icon__fallback" strokeWidth={1.8} />
      )}
    </span>
  )
}

import type { ReactElement } from 'react'
import { File } from 'lucide-react'
import { materialIconUrlByName } from 'virtual:material-icons'
import { materialIconNameForPath, type MaterialIconOptions } from '../../lib/file-icon'

function materialIconUrl(name: string): string | null {
  const closed = name.endsWith('-open') ? name.slice(0, -5) : null
  return materialIconUrlByName[name] ??
    (closed ? materialIconUrlByName[closed] : undefined) ??
    materialIconUrlByName.file ?? null
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
  const src = materialIconUrl(materialIconNameForPath(path, { directory, expanded }))
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

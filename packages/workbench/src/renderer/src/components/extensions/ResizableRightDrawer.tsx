import {
  useCallback,
  useEffect,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactElement,
  type ReactNode
} from 'react'
import { useTranslation } from 'react-i18next'

const WIDTH_KEY = 'deepseekgui.marketplace.drawerWidth'
const MIN_WIDTH = 320
const MAX_FRACTION = 0.7
const INITIAL_FRACTION = 1 / 3

function clampDrawerWidth(width: number, viewport = window.innerWidth): number {
  const max = Math.max(MIN_WIDTH, Math.round(viewport * MAX_FRACTION))
  return Math.min(max, Math.max(MIN_WIDTH, Math.round(width)))
}

function loadDrawerWidth(): number {
  try {
    const raw = window.localStorage.getItem(WIDTH_KEY)
    const parsed = raw ? Number(raw) : NaN
    if (Number.isFinite(parsed) && parsed > 0) return clampDrawerWidth(parsed)
  } catch {
    /* localStorage may be unavailable */
  }
  return clampDrawerWidth(window.innerWidth * INITIAL_FRACTION)
}

function saveDrawerWidth(width: number): void {
  try {
    window.localStorage.setItem(WIDTH_KEY, String(width))
  } catch {
    /* localStorage may be unavailable */
  }
}

type Props = {
  onClose: () => void
  children: ReactNode
}

export function ResizableRightDrawer({ onClose, children }: Props): ReactElement {
  const { t } = useTranslation('common')
  const [width, setWidth] = useState(() => loadDrawerWidth())

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    const onResize = (): void => {
      setWidth((current) => clampDrawerWidth(current))
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const beginResize = useCallback((event: ReactPointerEvent<HTMLDivElement>): void => {
    if (event.button !== 0) return
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    const startX = event.clientX
    const startWidth = width
    const prevCursor = document.body.style.cursor
    const prevUserSelect = document.body.style.userSelect
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    const onMove = (moveEvent: PointerEvent): void => {
      const next = clampDrawerWidth(startWidth + (startX - moveEvent.clientX))
      setWidth(next)
    }
    const onUp = (upEvent: PointerEvent): void => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      document.body.style.cursor = prevCursor
      document.body.style.userSelect = prevUserSelect
      try {
        event.currentTarget.releasePointerCapture(upEvent.pointerId)
      } catch {
        /* capture may already be released */
      }
      setWidth((current) => {
        const clamped = clampDrawerWidth(current)
        saveDrawerWidth(clamped)
        return clamped
      })
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }, [width])

  return (
    <>
      <button
        type="button"
        aria-label={t('pluginCloseDetail')}
        className="fixed inset-0 z-[80] bg-black/20 dark:bg-black/40"
        onClick={onClose}
      />
      <div
        className="ds-automation-drawer ds-no-drag fixed inset-y-0 right-0 z-[90] flex flex-col"
        style={{ width }}
      >
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label={t('marketplaceDrawerResize')}
          className="absolute inset-y-0 left-0 z-10 w-2 cursor-col-resize hover:bg-accent/20"
          onPointerDown={beginResize}
        />
        {children}
      </div>
    </>
  )
}

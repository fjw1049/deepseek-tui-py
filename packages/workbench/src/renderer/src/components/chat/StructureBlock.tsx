import { Check, Copy } from 'lucide-react'
import { useEffect, useRef, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'

type Props = {
  content: string
  actionsDisabled?: boolean
}

const COPY_RESET_MS = 2000

export function StructureBlock({ content, actionsDisabled = false }: Props): ReactElement {
  const { t } = useTranslation('common')
  const [isCopied, setIsCopied] = useState(false)
  const copyResetRef = useRef<number | null>(null)
  const trimmed = content.replace(/\n+$/u, '')

  useEffect(
    () => () => {
      if (copyResetRef.current !== null) window.clearTimeout(copyResetRef.current)
    },
    []
  )

  const handleCopy = async (): Promise<void> => {
    if (!navigator?.clipboard?.writeText) return
    await navigator.clipboard.writeText(trimmed)
    setIsCopied(true)
    if (copyResetRef.current !== null) window.clearTimeout(copyResetRef.current)
    copyResetRef.current = window.setTimeout(() => setIsCopied(false), COPY_RESET_MS)
  }

  return (
    <div className="ds-structure-block" data-streamdown="structure-block">
      <div className="ds-structure-block-header">
        <span className="ds-structure-block-label">{t('structureBlockLabel')}</span>
        <div className="ds-structure-block-actions">
          <button
            type="button"
            className="ds-code-block-action"
            title={t('structureBlockCopy')}
            aria-label={t('structureBlockCopy')}
            onClick={() => void handleCopy()}
            disabled={actionsDisabled}
          >
            {isCopied ? (
              <Check className="h-3.5 w-3.5" strokeWidth={2.1} />
            ) : (
              <Copy className="h-3.5 w-3.5" strokeWidth={1.9} />
            )}
          </button>
        </div>
      </div>
      <pre className="ds-structure-block-body">{trimmed}</pre>
    </div>
  )
}

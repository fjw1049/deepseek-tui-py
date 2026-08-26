import { useEffect, useState, type ReactElement } from 'react'
import { createPortal } from 'react-dom'
import { AlertCircle, Loader2, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { MarketplaceDocMarkdown } from './marketplace-ui'
import { ResizableRightDrawer } from './ResizableRightDrawer'

type Props = {
  /** Skill folder id/name, or null when the dialog is closed. */
  skillName: string | null
  title?: string
  skillsDir: string
  onClose: () => void
}

export function SkillPreviewDialog({ skillName, title, skillsDir, onClose }: Props): ReactElement | null {
  const { t } = useTranslation('common')
  const [content, setContent] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const open = skillName !== null

  useEffect(() => {
    if (!skillName || typeof window.dsGui?.readSkillDoc !== 'function') return
    let cancelled = false
    setLoading(true)
    setError(null)
    setContent('')
    void window.dsGui
      .readSkillDoc(skillsDir, skillName)
      .then((result) => {
        if (cancelled) return
        if (result.ok) {
          setContent(result.content)
        } else {
          setError(result.message ?? t('skillPreviewError'))
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [skillName, skillsDir, t])

  if (!open || typeof document === 'undefined') return null

  return createPortal(
    <ResizableRightDrawer onClose={onClose}>
      <div className="flex items-start justify-between gap-3 border-b border-ds-border-muted px-5 py-3.5">
        <h2 className="min-w-0 truncate text-[15px] font-semibold tracking-[-0.015em] text-ds-ink">
          {title || skillName}
        </h2>
        <button
          type="button"
          title={t('pluginCloseDetail')}
          onClick={onClose}
          className="inline-flex shrink-0 items-center gap-1 rounded-md border border-ds-border px-2.5 py-1.5 text-[12px] text-ds-muted hover:bg-ds-hover"
        >
          <X className="h-3.5 w-3.5" />
          {t('pluginCloseDetail')}
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-5 py-5">
        {loading ? (
          <div className="flex items-center gap-2 py-8 text-[13px] text-ds-muted">
            <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
            {t('skillsLoading')}
          </div>
        ) : error ? (
          <div className="flex items-start gap-2 rounded-xl border border-red-300/70 bg-red-50 px-4 py-3 text-[13px] leading-6 text-red-800 dark:border-red-800/60 dark:bg-red-950/25 dark:text-red-200">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={1.9} />
            <span className="min-w-0 break-words">{error}</span>
          </div>
        ) : content.trim() ? (
          <MarketplaceDocMarkdown content={content} />
        ) : (
          <p className="text-[13px] text-ds-faint">{t('marketplaceDocEmpty')}</p>
        )}
      </div>
    </ResizableRightDrawer>,
    document.body
  )
}

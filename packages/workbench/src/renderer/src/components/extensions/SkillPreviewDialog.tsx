import { useEffect, useState, type ReactElement } from 'react'
import { createPortal } from 'react-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { AlertCircle, Loader2, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'

type Props = {
  /** Skill folder id/name, or null when the dialog is closed. */
  skillName: string | null
  skillsDir: string
  onClose: () => void
}

/** Strip the YAML frontmatter block so the preview shows the readable body. */
function stripFrontmatter(content: string): string {
  return content.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '').trimStart()
}

export function SkillPreviewDialog({ skillName, skillsDir, onClose }: Props): ReactElement | null {
  const { t } = useTranslation('common')
  const [content, setContent] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const open = skillName !== null

  useEffect(() => {
    if (!open) return
    const handleKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [open, onClose])

  useEffect(() => {
    if (!skillName || typeof window.dsGui?.readSkill !== 'function') return
    let cancelled = false
    setLoading(true)
    setError(null)
    setContent('')
    void window.dsGui
      .readSkill(skillsDir, skillName)
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

  const body = stripFrontmatter(content)

  return createPortal(
    <div
      className="ds-modal-backdrop ds-no-drag fixed inset-0 z-[80] flex items-center justify-center p-4"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="ds-content-card flex max-h-[88vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl shadow-xl">
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-ds-border-muted px-5 py-3.5">
          <h2 className="min-w-0 truncate text-[16px] font-semibold text-ds-ink">{skillName}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('close')}
            title={t('close')}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
          >
            <X className="h-4 w-4" strokeWidth={1.9} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
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
          ) : (
            <div className="ds-markdown text-[14px] leading-7 text-ds-ink">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body
  )
}

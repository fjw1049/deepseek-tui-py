import { useEffect, useRef, useState, type ReactElement } from 'react'
import { Loader2, Upload } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { normalizePluginId } from './marketplace-shared'

type Props = {
  open: boolean
  skillsDir: string
  onClose: () => void
  /** Called after a successful install with the resulting SKILL.md path. */
  onInstalled: (path: string) => void
}

/** Pull the `name:` value out of a SKILL.md YAML frontmatter block. */
function parseFrontmatterName(content: string): string {
  const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---/)
  if (!match) return ''
  const line = match[1].split(/\r?\n/).find((l) => /^name\s*:/.test(l))
  if (!line) return ''
  return line.replace(/^name\s*:/, '').trim().replace(/^["']|["']$/g, '')
}

export function InstallSkillDialog({ open, skillsDir, onClose, onInstalled }: Props): ReactElement | null {
  const { t } = useTranslation('common')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

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
    if (!open) return
    setBusy(false)
    setError(null)
    setDragActive(false)
  }, [open])

  if (!open) return null

  const installMarkdown = async (file: File): Promise<void> => {
    if (typeof window.dsGui?.saveSkillFile !== 'function') return
    const content = await file.text()
    const derived = parseFrontmatterName(content) || file.name.replace(/\.md$/i, '')
    const id = normalizePluginId(derived) || 'skill'
    const result = await window.dsGui.saveSkillFile(skillsDir, id, content)
    if (!result.ok) {
      setError(result.message)
      return
    }
    onInstalled(result.path)
    onClose()
  }

  const installZip = async (file: File, overwrite: boolean): Promise<void> => {
    if (typeof window.dsGui?.installSkillZip !== 'function') return
    const data = new Uint8Array(await file.arrayBuffer())
    const result = await window.dsGui.installSkillZip({
      rootPath: skillsDir,
      fileName: file.name,
      data,
      overwrite
    })
    if (result.ok) {
      onInstalled(result.path)
      onClose()
      return
    }
    if (result.conflict) {
      // `message` carries the conflicting skill name from the main process.
      if (window.confirm(t('skillInstallConflict', { name: result.message ?? file.name }))) {
        await installZip(file, true)
      }
      return
    }
    setError(result.message ?? t('skillInstallBadType'))
  }

  const handleFile = async (file: File): Promise<void> => {
    setBusy(true)
    setError(null)
    try {
      const lower = file.name.toLowerCase()
      if (lower.endsWith('.zip')) {
        await installZip(file, false)
      } else if (lower.endsWith('.md')) {
        await installMarkdown(file)
      } else {
        setError(t('skillInstallBadType'))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="ds-content-card absolute right-0 top-full z-20 mt-1.5 w-80 overflow-hidden rounded-2xl p-4 shadow-lg">
      <div className="mb-3 text-[14px] font-semibold text-ds-ink">{t('skillInstallTitle')}</div>
      <input
        ref={inputRef}
        type="file"
        accept=".zip,.md"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0]
          event.target.value = ''
          if (file) void handleFile(file)
        }}
      />
      <button
        type="button"
        disabled={busy}
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault()
          setDragActive(true)
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragActive(false)
          const file = event.dataTransfer.files?.[0]
          if (file) void handleFile(file)
        }}
        className={`flex w-full flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-6 py-8 text-center transition ${
          dragActive ? 'border-accent/60 bg-accent/5' : 'border-ds-border bg-ds-main/30 hover:bg-ds-subtle/40'
        } disabled:cursor-not-allowed disabled:opacity-60`}
      >
        {busy ? (
          <Loader2 className="h-6 w-6 animate-spin text-ds-muted" strokeWidth={1.75} />
        ) : (
          <Upload className="h-6 w-6 text-ds-muted" strokeWidth={1.6} />
        )}
        <div className="text-[14px] font-semibold text-ds-ink">
          {busy ? t('skillInstallInstalling') : t('skillInstallDropHint')}
        </div>
        {!busy ? <div className="text-[12px] text-ds-muted">{t('skillInstallClickHint')}</div> : null}
        <div className="mt-1 text-[11px] text-ds-faint">{t('skillInstallFormats')}</div>
      </button>

      {error ? (
        <div className="mt-3 rounded-xl border border-red-300/70 bg-red-50 px-3 py-2 text-[13px] text-red-800 dark:border-red-800/60 dark:bg-red-950/25 dark:text-red-200">
          {error}
        </div>
      ) : null}
    </div>
  )
}

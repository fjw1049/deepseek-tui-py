import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement
} from 'react'
import { Check, Hand, Shield, Zap } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  sandboxModeForApprovalPolicy,
  type ApprovalPolicy
} from '@shared/app-settings'
import { useComboboxNav } from '../../hooks/use-combobox-nav'
import { useLightDismiss } from '../../hooks/use-light-dismiss'
import { OPEN_APPROVAL_POLICY_EVENT } from '../../lib/shortcuts-runtime'
import { useChatStore } from '../../store/chat-store'

/**
 * Composer shortcut for the three most-used approval policies that already
 * exist in Settings → Permissions. Values are the real `ApprovalPolicy`
 * enum members — never invent labels that belong to sandbox mode.
 */
export type ComposerApprovalTier = Extract<ApprovalPolicy, 'on-request' | 'untrusted' | 'auto'>

type Props = {
  disabled?: boolean
  onOpenChange?: (open: boolean) => void
  /** Hide the text label; keep the icon + title tooltip. */
  compact?: boolean
  /** IDE rail: shorter trigger matching 12px chat chrome. */
  dense?: boolean
}

// auto = soft amber; untrusted = pale gold; on-request = pale green
const tierAccent: Record<ComposerApprovalTier, string> = {
  auto: '#e0a04a',
  untrusted: '#c9b06a',
  'on-request': '#7eab8a'
}

export function ComposerApprovalPolicySelector({
  disabled = false,
  onOpenChange,
  compact = false,
  dense = false
}: Props): ReactElement {
  const { t } = useTranslation(['common', 'settings'])
  const probeRuntime = useChatStore((s) => s.probeRuntime)
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const [open, setOpen] = useState(false)
  const [policy, setPolicy] = useState<ApprovalPolicy>('on-request')
  const [saving, setSaving] = useState(false)

  const setMenuOpen = useCallback(
    (next: boolean) => {
      setOpen(next)
      onOpenChange?.(next)
    },
    [onOpenChange]
  )

  const refreshPolicy = useCallback(async (): Promise<void> => {
    if (typeof window.dsGui?.getSettings !== 'function') return
    const settings = await window.dsGui.getSettings()
    setPolicy(settings.deepseek.approvalPolicy)
  }, [])

  useEffect(() => {
    void refreshPolicy()
  }, [refreshPolicy])

  useEffect(() => {
    if (!open) return
    void refreshPolicy()
  }, [open, refreshPolicy])

  useLightDismiss({
    open,
    onDismiss: () => setMenuOpen(false),
    refs: [wrapRef],
    enabled: !disabled
  })

  useEffect(() => {
    const onOpenMenu = (): void => {
      if (disabled) return
      setMenuOpen(true)
    }
    window.addEventListener(OPEN_APPROVAL_POLICY_EVENT, onOpenMenu)
    return () => window.removeEventListener(OPEN_APPROVAL_POLICY_EVENT, onOpenMenu)
  }, [disabled, setMenuOpen])

  const triggerLabel =
    policy === 'auto'
      ? t('settings:approvalAuto')
      : policy === 'untrusted'
        ? t('settings:approvalUntrusted')
        : policy === 'never'
          ? t('settings:approvalNever')
          : policy === 'suggest'
            ? t('settings:approvalSuggest')
            : t('settings:approvalOnRequest')

  const TriggerIcon =
    policy === 'auto' ? Zap : policy === 'untrusted' ? Shield : Hand

  const triggerAccent =
    policy === 'auto' || policy === 'untrusted' || policy === 'on-request'
      ? tierAccent[policy]
      : undefined

  const options = useMemo(
    () => [
      {
        id: 'on-request' as const,
        title: t('settings:approvalOnRequest'),
        description: t('common:composerApprovalOnRequestDesc'),
        Icon: Hand,
        accent: tierAccent['on-request']
      },
      {
        id: 'untrusted' as const,
        title: t('settings:approvalUntrusted'),
        description: t('common:composerApprovalUntrustedDesc'),
        Icon: Shield,
        accent: tierAccent.untrusted
      },
      {
        id: 'auto' as const,
        title: t('settings:approvalAuto'),
        description: t('common:composerApprovalAutoDesc'),
        Icon: Zap,
        accent: tierAccent.auto
      }
    ],
    [t]
  )
  const { highlighted, setHighlighted, onKeyDown } = useComboboxNav(options.length, open)

  useEffect(() => {
    if (!open) return
    const index = options.findIndex((option) => option.id === policy)
    setHighlighted(index >= 0 ? index : 0)
  }, [open, options, policy, setHighlighted])

  const selectPolicy = async (next: ComposerApprovalTier): Promise<void> => {
    if (saving || next === policy) {
      setMenuOpen(false)
      return
    }
    if (typeof window.dsGui?.setSettings !== 'function') return
    setSaving(true)
    try {
      const updated = await window.dsGui.setSettings({
        deepseek: {
          approvalPolicy: next,
          sandboxMode: sandboxModeForApprovalPolicy(next)
        }
      })
      setPolicy(updated.deepseek.approvalPolicy)
      setMenuOpen(false)
      void probeRuntime('background')
    } catch {
      /* keep previous selection */
    } finally {
      setSaving(false)
    }
  }
  // The window key handler outlives renders; read the current policy/saving state.
  const selectPolicyRef = useRef(selectPolicy)
  selectPolicyRef.current = selectPolicy

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent): void => {
      if (event.isComposing || event.keyCode === 229) return
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        setMenuOpen(false)
        return
      }
      const handled = onKeyDown(event, (index) => {
        const option = options[index]
        if (option) void selectPolicyRef.current(option.id)
      })
      if (handled) event.stopPropagation()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onKeyDown, open, options, setMenuOpen])

  return (
    <div ref={wrapRef} className="relative shrink-0">
      <button
        type="button"
        disabled={disabled || saving}
        onClick={() => setMenuOpen(!open)}
        className={`ds-no-drag inline-flex shrink-0 select-none items-center gap-1.5 px-1 text-[13px] font-medium transition hover:opacity-80 disabled:cursor-not-allowed disabled:opacity-50 ${
          dense ? 'h-7' : 'h-9'
        }`}
        style={triggerAccent ? { color: triggerAccent } : undefined}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t('settings:approvalPolicy')}
        title={t('settings:approvalPolicy')}
      >
        <TriggerIcon
          className={`${dense ? 'h-3.5 w-3.5' : 'h-4 w-4'} shrink-0`}
          strokeWidth={2}
          aria-hidden
        />
        {compact ? null : (
          <span className={`truncate ${triggerAccent ? '' : 'text-ds-ink'}`}>{triggerLabel}</span>
        )}
      </button>

      {open ? (
        <div className="absolute bottom-full left-0 z-40 mb-2 w-[min(100vw-2rem,320px)]">
          <div role="menu" aria-label={t('settings:approvalPolicy')} className="ds-project-context-menu ds-composer-picker ds-morph-pop overflow-hidden p-1.5">
            <div className="ds-morph-stagger">
              {options.map((option, index) => {
                const selected = policy === option.id
                const OptionIcon = option.Icon
                return (
                  <button
                    key={option.id}
                    type="button"
                    role="menuitemradio"
                    aria-checked={selected}
                    disabled={saving}
                    onMouseDown={(event) => event.preventDefault()}
                    onMouseEnter={() => setHighlighted(index)}
                    onClick={() => void selectPolicy(option.id)}
                    className={`ds-project-context-menu__row ${selected ? 'ds-project-context-menu__row--active' : ''} ${highlighted === index ? 'ds-project-context-menu__row--highlight' : ''}`}
                  >
                    <span className="ds-project-context-menu__icon" aria-hidden>
                      <OptionIcon className="h-3.5 w-3.5" strokeWidth={1.85} style={{ color: option.accent }} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="ds-project-context-menu__row-title">{option.title}</span>
                      <span className="ds-project-context-menu__row-path whitespace-normal">
                        {option.description}
                      </span>
                    </span>
                    {selected ? (
                      <Check
                        className="h-4 w-4 shrink-0 text-accent"
                        strokeWidth={2.2}
                        aria-hidden
                      />
                    ) : (
                      <span className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                    )}
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ComponentProps,
  type ReactElement
} from 'react'
import { PawPrint } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { usePetController } from '../../hooks/use-pet-controller'
import {
  filterPetSlashMenu,
  parsePetSlashCommand,
  PET_SLASH_MENU
} from '../../lib/pet/pet-slash-commands'
import { useNoticeAutoDismiss, type Notice } from '../extensions/marketplace-shared'
import { PetMascotDock } from '../pet/PetMascotDock'
import { ComposerNoticeToast } from './composer-notice'
import { FloatingComposer } from './FloatingComposer'
import { GoalStrip } from './GoalStrip'

type Props = ComponentProps<typeof FloatingComposer> & {
  /** One-shot notice from parent (e.g. preview pick limit); keyed by nonce. */
  flashNotice?: Notice | null
  flashNoticeNonce?: number
}

const COMPOSER_CLEARANCE_VAR = '--ds-composer-clearance'
const MemoFloatingComposer = memo(FloatingComposer)

export function ComposerStage(props: Props): ReactElement {
  const { t } = useTranslation('common')
  const pet = usePetController()
  const rootRef = useRef<HTMLDivElement>(null)
  const [composerNotice, setComposerNotice] = useState<Notice | null>(null)
  useNoticeAutoDismiss(composerNotice, setComposerNotice)

  const { flashNotice = null, flashNoticeNonce = 0, ...composerProps } = props

  useEffect(() => {
    if (flashNoticeNonce > 0 && flashNotice) {
      setComposerNotice(flashNotice)
    }
  }, [flashNotice, flashNoticeNonce])

  const petSlashCommands = useMemo(
    () =>
      PET_SLASH_MENU.map((item) => ({
        command: item.command,
        token: item.token,
        title: t(item.titleKey),
        description: t(item.descriptionKey),
        icon: <PawPrint className="h-4 w-4" strokeWidth={1.8} />
      })),
    [t]
  )

  const handleSend = useCallback((text: string): Promise<boolean> => {
    if (pet.handlePetSlash(text)) return Promise.resolve(true)
    if (parsePetSlashCommand(text)?.type === 'unknown') {
      // Keep the draft so the typo can be fixed; it is not meant for the model.
      setComposerNotice({ tone: 'error', message: t('petSlashUnknown') })
      return Promise.resolve(false)
    }
    return composerProps.onSend(text)
  }, [composerProps.onSend, pet.handlePetSlash, t])

  // Timeline spacer follows real composer height (approvals /
  // queued messages) so overlapping chrome doesn't cover the last answer or
  // make the dialogue appear to jump when the tray mounts.
  useLayoutEffect(() => {
    const root = rootRef.current
    if (!root || typeof ResizeObserver === 'undefined') return
    const scope = root.closest<HTMLElement>('[data-chat-pane]') ?? document.documentElement
    const publish = (): void => {
      const height = Math.ceil(root.getBoundingClientRect().height)
      scope.style.setProperty(
        COMPOSER_CLEARANCE_VAR,
        `${Math.max(height, 0)}px`
      )
    }
    publish()
    const ro = new ResizeObserver(publish)
    ro.observe(root)
    return () => {
      ro.disconnect()
      scope.style.removeProperty(COMPOSER_CLEARANCE_VAR)
    }
  }, [])

  return (
    <div ref={rootRef} className="relative flex w-full flex-col items-stretch">
      {composerNotice ? (
        <div className="ds-chat-stage mb-1.5 flex w-full justify-center px-3 sm:px-4">
          <ComposerNoticeToast notice={composerNotice} onDismiss={() => setComposerNotice(null)} />
        </div>
      ) : null}
      <div className="relative">
        <GoalStrip />
        {/* Rests just above the input (bottom-full). Only the pet and its
            bubble take hits; the composer, painted later, keeps its popovers
            (the model picker) on top. */}
        {/* Mounted only once a sheet is ready, so its motion hooks start with real DOM. */}
        {pet.status !== 'hidden' ? <div className="pointer-events-none absolute bottom-full right-0 z-0">
          <PetMascotDock
            stateId={pet.stateId}
            playKey={pet.playKey}
            spritesheetSrc={pet.spritesheetSrc}
            petName={pet.petName}
            bubble={pet.bubble}
            hearts={pet.hearts}
            canStroll={pet.canStroll}
            motionPaused={pet.motionPaused}
            onActivate={pet.activate}
            onHoverChange={pet.setHovered}
            onBubbleAction={pet.onBubbleAction}
          />
        </div> : null}
        <MemoFloatingComposer
          {...composerProps}
          onNoticeChange={setComposerNotice}
          onSend={handleSend}
          petSlashCommands={petSlashCommands}
          onApplyPetSlashCommand={pet.handlePetSlash}
          filterPetSlashCommands={filterPetSlashMenu}
        />
      </div>
    </div>
  )
}

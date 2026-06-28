import { useMemo, useState, type ComponentProps, type ReactElement } from 'react'
import { PawPrint } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { usePetController } from '../../hooks/use-pet-controller'
import { filterPetSlashMenu, PET_SLASH_MENU } from '../../lib/pet/pet-slash-commands'
import { PetMascotDock } from '../pet/PetMascotDock'
import { FloatingComposer } from './FloatingComposer'
import { ProcessTray } from './ProcessTray'

type Props = ComponentProps<typeof FloatingComposer>

export function ComposerStage(props: Props): ReactElement {
  const { t } = useTranslation('common')
  const pet = usePetController()
  const [composerNotice, setComposerNotice] = useState<string | null>(null)

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

  const handleSend = (text: string): void => {
    if (pet.handlePetSlash(text)) return
    props.onSend(text)
  }

  return (
    <div className="flex w-full flex-col items-stretch">
      <div className="relative">
        <div className="ds-chat-stage flex w-full px-3 sm:px-4">
          <div className="ds-no-drag min-w-0 flex-1">
            <ProcessTray />
          </div>
        </div>
        {/* The pet is decorative and doesn't block reading, so it overlays the
            area above the input instead of reserving a row — letting content
            extend down to just above the composer. */}
        <div className="pointer-events-none absolute bottom-0 right-0 z-[5]">
          <PetMascotDock
            visible
            status={pet.status}
            stateId={pet.stateId}
            spritesheetSrc={pet.spritesheetSrc}
            roamOffset={pet.roamOffset}
            motionPaused={pet.motionPaused}
          />
        </div>
      </div>
      {composerNotice ? (
        <div className="ds-chat-stage mb-1.5 flex w-full justify-center px-3 sm:px-4">
          <p className="max-w-[min(100%,560px)] text-center text-[12px] leading-5 text-ds-faint">
            {composerNotice}
          </p>
        </div>
      ) : null}
      <FloatingComposer
        {...props}
        onNoticeChange={setComposerNotice}
        onSend={handleSend}
        petSlashCommands={petSlashCommands}
        onApplyPetSlashCommand={pet.handlePetSlash}
        filterPetSlashCommands={filterPetSlashMenu}
      />
    </div>
  )
}

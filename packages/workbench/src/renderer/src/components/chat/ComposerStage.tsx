import type { ComponentProps, ReactElement } from 'react'
import { useMemo } from 'react'
import { PawPrint } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { usePetController } from '../../hooks/use-pet-controller'
import { filterPetSlashMenu, PET_SLASH_MENU } from '../../lib/pet/pet-slash-commands'
import { PetMascotDock } from '../pet/PetMascotDock'
import { FloatingComposer } from './FloatingComposer'

type Props = ComponentProps<typeof FloatingComposer>

export function ComposerStage(props: Props): ReactElement {
  const { t } = useTranslation('common')
  const pet = usePetController()

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
    <div className="flex w-full flex-col items-center">
      <PetMascotDock
        visible
        status={pet.status}
        stateId={pet.stateId}
        spritesheetSrc={pet.spritesheetSrc}
        roamOffset={pet.roamOffset}
      />
      <FloatingComposer
        {...props}
        onSend={handleSend}
        petSlashCommands={petSlashCommands}
        onApplyPetSlashCommand={pet.handlePetSlash}
        filterPetSlashCommands={filterPetSlashMenu}
      />
    </div>
  )
}

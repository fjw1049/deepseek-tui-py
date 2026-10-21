import { useTranslation } from 'react-i18next'

export function PluginDescription({ copyKey }: { copyKey: string }): React.JSX.Element {
  const { t } = useTranslation('common')
  return <div className="mt-6 space-y-5 text-sm leading-6">
    <p className="text-ds-muted">{t(`${copyKey}Intro`)}</p>
    <section>
      <h3 className="font-medium">{t('pluginCapabilitiesLabel')}</h3>
      <ul className="mt-2 space-y-2 text-ds-muted">
        {[1, 2, 3].map(index => <li key={index} className="flex gap-2">
          <span aria-hidden="true">·</span><span>{t(`${copyKey}Capability${index}`)}</span>
        </li>)}
      </ul>
    </section>
    <section>
      <h3 className="font-medium">{t('pluginDeliverablesLabel')}</h3>
      <p className="mt-2 text-ds-muted">{t(`${copyKey}Deliverables`)}</p>
    </section>
    <div className="rounded-xl bg-ds-subtle/60 p-4">
      <h3 className="text-xs font-medium text-ds-muted">{t('pluginExampleLabel')}</h3>
      <p className="mt-2">{t(`${copyKey}Example`)}</p>
    </div>
  </div>
}

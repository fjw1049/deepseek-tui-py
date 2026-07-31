import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import enCommon from './locales/en/common.json'
import zhCommon from './locales/zh/common.json'
import enSettings from './locales/en/settings.json'
import zhSettings from './locales/zh/settings.json'

void i18n.use(initReactI18next).init({
  resources: {
    en: { common: enCommon, settings: enSettings },
    zh: { common: zhCommon, settings: zhSettings }
  },
  lng: 'en',
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
  defaultNS: 'common',
  ns: ['common', 'settings']
})

// Locale JSON has no Fast Refresh boundary — without this, any touch forces a
// full page reload (and kicks the UI back to the greeting screen).
if (import.meta.hot) {
  const localeDeps = [
    './locales/en/common.json',
    './locales/zh/common.json',
    './locales/en/settings.json',
    './locales/zh/settings.json'
  ] as const
  import.meta.hot.accept(localeDeps as unknown as string[], (mods) => {
    const bundles: Array<['en' | 'zh', 'common' | 'settings', { default?: object } | undefined]> = [
      ['en', 'common', mods?.[0]],
      ['zh', 'common', mods?.[1]],
      ['en', 'settings', mods?.[2]],
      ['zh', 'settings', mods?.[3]]
    ]
    for (const [lng, ns, mod] of bundles) {
      if (mod?.default) i18n.addResourceBundle(lng, ns, mod.default, true, true)
    }
  })
}

export default i18n

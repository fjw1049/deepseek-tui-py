import React from 'react'
import ReactDOM from 'react-dom/client'
import './fonts.css'
import './index.css'
import App from './App'
import './i18n'

document.documentElement.dataset.platform = window.dsGui?.platform ?? 'unknown'
document.documentElement.setAttribute('data-ui-font', 'inter-noto')

// Monaco and xterm cache glyph sizes. Load the local fonts before mounting
// either surface so the first measurements never use system fallbacks.
void Promise.all([
  document.fonts.load('400 14px Inter'),
  document.fonts.load('400 14px "JetBrains Mono"'),
  document.fonts.load('400 14px "Noto Sans SC"', '中文')
]).catch((error) => {
  console.warn('Bundled fonts could not be loaded', error)
}).then(() => {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  )
})

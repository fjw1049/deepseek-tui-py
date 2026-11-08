import React from 'react'
import ReactDOM from 'react-dom/client'
import './fonts.css'
import './index.css'
import App from './App'
import './i18n'

document.documentElement.dataset.platform = window.dsGui?.platform ?? 'unknown'
document.documentElement.setAttribute('data-ui-font', 'inter-noto')

// Load the code font before Monaco and xterm measure their character cells.
void document.fonts.load('400 14px "JetBrains Mono"').catch((error) => {
  console.warn('Code font could not be loaded', error)
}).then(() => {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  )
})

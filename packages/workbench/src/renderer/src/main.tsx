import React from 'react'
import ReactDOM from 'react-dom/client'
import './fonts.css'
import './index.css'
import App from './App'
import './i18n'

document.documentElement.dataset.platform = window.dsGui?.platform ?? 'unknown'
document.documentElement.setAttribute('data-ui-font', 'system-native')

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)

import { Menu, type MenuItemConstructorOptions } from 'electron'

/** Name users see; packaged builds keep the legacy app.name for their keychain entry. */
export const APP_DISPLAY_NAME = 'Dayu'

/**
 * Install a minimal app menu that frees ⌘Q for the in-app approval-policy
 * shortcut. Quit moves to ⌘⇧Q (still available from the macOS app menu).
 */
export function installAppMenu(): void {
  const isMac = process.platform === 'darwin'
  const quitItem: MenuItemConstructorOptions = {
    role: 'quit',
    // Reclaim ⌘Q for renderer shortcuts; keep an explicit quit chord.
    accelerator: isMac ? 'Command+Shift+Q' : 'Ctrl+Shift+Q'
  }

  const template: MenuItemConstructorOptions[] = isMac
    ? [
        {
          label: APP_DISPLAY_NAME,
          submenu: [
            { role: 'about', label: `About ${APP_DISPLAY_NAME}` },
            { type: 'separator' },
            { role: 'services' },
            { type: 'separator' },
            { role: 'hide', label: `Hide ${APP_DISPLAY_NAME}` },
            { role: 'hideOthers' },
            { role: 'unhide' },
            { type: 'separator' },
            { ...quitItem, label: `Quit ${APP_DISPLAY_NAME}` }
          ]
        },
        {
          label: 'Edit',
          submenu: [
            { role: 'undo' },
            { role: 'redo' },
            { type: 'separator' },
            { role: 'cut' },
            { role: 'copy' },
            { role: 'paste' },
            { role: 'pasteAndMatchStyle' },
            { role: 'delete' },
            { role: 'selectAll' }
          ]
        },
        {
          label: 'View',
          submenu: [
            { role: 'reload' },
            { role: 'toggleDevTools' },
            { type: 'separator' },
            { role: 'resetZoom' },
            { role: 'zoomIn' },
            { role: 'zoomOut' },
            { type: 'separator' },
            { role: 'togglefullscreen' }
          ]
        },
        {
          label: 'Window',
          submenu: [
            { role: 'minimize' },
            { role: 'zoom' },
            { type: 'separator' },
            { role: 'front' }
          ]
        }
      ]
    : [
        {
          label: 'File',
          submenu: [quitItem]
        },
        {
          label: 'Edit',
          submenu: [
            { role: 'undo' },
            { role: 'redo' },
            { type: 'separator' },
            { role: 'cut' },
            { role: 'copy' },
            { role: 'paste' },
            { role: 'delete' },
            { role: 'selectAll' }
          ]
        },
        {
          label: 'View',
          submenu: [
            { role: 'reload' },
            { role: 'toggleDevTools' },
            { type: 'separator' },
            { role: 'resetZoom' },
            { role: 'zoomIn' },
            { role: 'zoomOut' },
            { type: 'separator' },
            { role: 'togglefullscreen' }
          ]
        }
      ]

  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

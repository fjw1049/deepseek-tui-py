if (typeof window !== 'undefined' && typeof document !== 'undefined' &&
    typeof window.localStorage?.clear !== 'function') {
  const { Storage } = await import('happy-dom')
  Object.defineProperty(window, 'localStorage', { configurable: true, value: new Storage() })
}
export {}

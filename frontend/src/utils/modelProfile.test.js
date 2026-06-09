import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

function createLocalStorageMock() {
  let store = new Map()
  return {
    getItem: vi.fn((key) => store.get(String(key)) ?? null),
    setItem: vi.fn((key, value) => store.set(String(key), String(value))),
    removeItem: vi.fn((key) => store.delete(String(key))),
    clear: vi.fn(() => {
      store = new Map()
    }),
  }
}

beforeEach(() => {
  vi.resetModules()
  vi.stubGlobal('localStorage', createLocalStorageMock())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('model profile display name', () => {
  it('uses the product model name when no stored value exists', async () => {
    const { getModelDisplayName, modelDisplayName } = await import('./modelProfile')

    expect(modelDisplayName.value).toBe('OURAI')
    expect(getModelDisplayName()).toBe('OURAI')
  })

  it('seeds the reactive display name from local storage', async () => {
    localStorage.setItem('ai4ml-model-display-name', 'OURAI')

    const { getModelDisplayName, modelDisplayName } = await import('./modelProfile')

    expect(modelDisplayName.value).toBe('OURAI')
    expect(getModelDisplayName()).toBe('OURAI')
  })

  it('updates the shared reactive value and local storage together', async () => {
    const { getModelDisplayName, modelDisplayName, setModelDisplayName } = await import('./modelProfile')

    const nextName = setModelDisplayName('Team Model')

    expect(nextName).toBe('Team Model')
    expect(modelDisplayName.value).toBe('Team Model')
    expect(getModelDisplayName()).toBe('Team Model')
    expect(localStorage.getItem('ai4ml-model-display-name')).toBe('Team Model')
  })
})

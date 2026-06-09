import { ref } from 'vue'

const DEFAULT_MODEL_DISPLAY_NAME = 'OURAI'

const STORAGE_KEY = 'ai4ml-model-display-name'

function readStoredName() {
  try {
    return globalThis.localStorage?.getItem(STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

function writeStoredName(value) {
  try {
    globalThis.localStorage?.setItem(STORAGE_KEY, value)
  } catch {
    // Local storage is optional in tests and private browsing modes.
  }
}

function normalizeModelDisplayName(value) {
  const name = String(value || '').trim()
  return name ? name.slice(0, 48) : DEFAULT_MODEL_DISPLAY_NAME
}

export const modelDisplayName = ref(normalizeModelDisplayName(readStoredName()))

export function setModelDisplayName(value) {
  const next = normalizeModelDisplayName(value)
  modelDisplayName.value = next
  writeStoredName(next)
  return next
}

export function getModelDisplayName() {
  return modelDisplayName.value || DEFAULT_MODEL_DISPLAY_NAME
}

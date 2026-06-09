import { optionalRequest, request } from '@/api/request'
import { getActiveTeamHint } from '@/api/session'
import { getModelDisplayName } from '@/utils/modelProfile'

const MODEL_PROFILE_CACHE_PREFIX = 'ai4ml-model-profile-cache-v1'
const MODEL_PROFILE_CACHE_TTL_MS = 10 * 60 * 1000

export async function getModelProfile(options = {}) {
  const cacheKey = modelProfileCacheKey()
  if (!options.forceRefresh) {
    const cached = readModelProfileCache(cacheKey)
    if (cached) return cached
  }
  const profile = await optionalRequest('/model-config/profile', {}, { display_name: getModelDisplayName() })
  writeModelProfileCache(cacheKey, profile)
  return profile
}

export async function getModelConfig() {
  return request('/model-config')
}

export async function updateModelConfig(payload) {
  const result = await request('/model-config', {
    method: 'PUT',
    body: JSON.stringify({
      display_name: payload.display_name,
      api_key: payload.api_key || '',
      config_toml: payload.config_toml,
    }),
  })
  writeModelProfileCache(modelProfileCacheKey(), {
    display_name: result?.display_name || payload.display_name || getModelDisplayName(),
    auth_configured: Boolean(result?.auth_configured),
  })
  return result
}

function modelProfileCacheKey() {
  const teamId = getActiveTeamHint()?.id || 'default'
  return `${MODEL_PROFILE_CACHE_PREFIX}:${teamId}`
}

function readModelProfileCache(cacheKey) {
  if (typeof localStorage === 'undefined') return null
  try {
    const payload = JSON.parse(localStorage.getItem(cacheKey) || 'null')
    if (!payload || !payload.profile) return null
    if (Date.now() - Number(payload.cached_at || 0) >= MODEL_PROFILE_CACHE_TTL_MS) return null
    return payload.profile
  } catch {
    return null
  }
}

function writeModelProfileCache(cacheKey, profile) {
  if (typeof localStorage === 'undefined') return
  localStorage.setItem(cacheKey, JSON.stringify({
    cached_at: Date.now(),
    profile,
  }))
}

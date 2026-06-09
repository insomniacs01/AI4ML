import { localizeError } from '@/api/errors'
import { optionalRequest } from '@/api/request'
import {
  DEFAULT_TEAM_NAME,
  createTeam,
  ensureActiveTeam,
  ensureMemberships,
  normalizeRole,
  requireSession,
  requireSupabase,
  resetAuthCaches,
  setCachedAuth,
} from '@/api/session'

const PROFILE_QUOTA_CACHE_PREFIX = 'ai4ml-profile-quota-cache-v1'
const PROFILE_QUOTA_CACHE_TTL_MS = 60 * 1000
const PROFILE_QUOTA_STALE_CACHE_TTL_MS = 10 * 60 * 1000
const pendingProfileQuotaRefreshes = new Map()
let pendingTeamMembershipRefresh = null

async function ensureTeamMembership() {
  const memberships = await ensureMemberships()
  if (!memberships.length) await createTeam(DEFAULT_TEAM_NAME)
  else refreshTeamMembershipSoon()
}

function refreshTeamMembershipSoon(delayMs = 1200) {
  if (pendingTeamMembershipRefresh) return
  pendingTeamMembershipRefresh = globalThis.setTimeout(() => {
    pendingTeamMembershipRefresh = null
    ensureMemberships(true)
      .then(async (memberships) => {
        if (!memberships.length) await createTeam(DEFAULT_TEAM_NAME)
      })
      .catch(() => {})
  }, delayMs)
}

export async function login(payload) {
  const client = requireSupabase()
  const email = String(payload.email || payload.user_id || '').trim()
  const password = String(payload.password || '')
  const { data, error } = await client.auth.signInWithPassword({ email, password })
  if (error) throw new Error(localizeError(error.message, 401))
  await resetAuthCaches({ clearStoredMemberships: false })
  setCachedAuth(data.session, data.user)
  refreshTeamMembershipSoon(0)
  return profileFromAuthUser(data.user)
}

export async function register(payload) {
  const client = requireSupabase()
  const email = String(payload.email || payload.user_id || '').trim()
  const password = String(payload.password || '')
  const displayName = String(payload.display_name || payload.displayName || '').trim()
  const { data, error } = await client.auth.signUp({
    email,
    password,
    options: { data: { display_name: displayName } },
  })
  if (error) throw new Error(localizeError(error.message, 400))
  await resetAuthCaches({ clearStoredMemberships: false })
  setCachedAuth(data.session || null, data.user || null)
  if (data.session?.access_token) {
    await ensureTeamMembership()
  }
  return { user: data.user, session: data.session || null }
}

export async function changePassword(payload) {
  const client = requireSupabase()
  const { error } = await client.auth.updateUser({ password: payload.new_password })
  if (error) throw new Error(localizeError(error.message, 400))
  return { ok: true }
}

export async function logout() {
  const client = requireSupabase()
  await client.auth.signOut()
  await resetAuthCaches()
  return { ok: true }
}

export async function getMe() {
  const session = await requireSession()
  let memberships = await ensureMemberships()
  if (!memberships.length) {
    await createTeam(DEFAULT_TEAM_NAME)
    memberships = await ensureMemberships(true)
  }
  const activeTeam = memberships.length ? await ensureActiveTeam() : null
  const metadata = session.user.user_metadata || {}
  return {
    user: {
      user_id: session.user.id,
      email: session.user.email,
      display_name: metadata.display_name || session.user.email || session.user.id,
      role: normalizeRole(activeTeam?.role),
      native_role: activeTeam?.role || '',
      active_team_id: activeTeam?.id || '',
      active_team_name: activeTeam?.name || '',
      memberships,
    },
  }
}

export async function getCurrentUser() {
  return getMe()
}

export async function getProfile() {
  const me = await getMe()
  const cacheKey = profileQuotaCacheKey(me.user)
  const cachedQuota = readProfileQuotaCache(cacheKey)
  if (cachedQuota) return profileFromQuota(me.user, cachedQuota)
  const staleQuota = readProfileQuotaCache(cacheKey, { allowStale: true })
  if (staleQuota) {
    refreshProfileQuotaInBackground(cacheKey)
    return profileFromQuota(me.user, staleQuota)
  }
  return profileFromQuota(me.user, await fetchProfileQuota(cacheKey))
}

export async function getProfileBase() {
  const me = await getMe()
  const cacheKey = profileQuotaCacheKey(me.user)
  const cachedQuota = readProfileQuotaCache(cacheKey, { allowStale: true })
  return cachedQuota
    ? profileFromQuota(me.user, cachedQuota)
    : profileFromBaseUser(me.user)
}

function profileFromAuthUser(user) {
  const metadata = user?.user_metadata || {}
  return {
    user: {
      user_id: user?.id || '',
      email: user?.email || '',
      display_name: metadata.display_name || user?.email || user?.id || '',
      role: 'business',
      native_role: '',
      active_team_id: '',
      active_team_name: '',
      memberships: [],
    },
  }
}

function profileFromBaseUser(user) {
  return {
    ...user,
    token_quota: null,
    token_used: null,
    token_remaining: null,
    quota_status: '',
    quota_loaded: false,
  }
}

function profileFromQuota(user, quota) {
  const mine = quota || {}
  return {
    ...user,
    token_quota: mine.token_quota || 0,
    token_used: mine.token_used || 0,
    token_remaining: mine.token_remaining ?? Math.max(0, Number(mine.token_quota || 0) - Number(mine.token_used || 0)),
    quota_status: mine.status || 'active',
    quota_loaded: true,
  }
}

export async function updateProfile(payload) {
  const client = requireSupabase()
  const { data, error } = await client.auth.updateUser({ data: { display_name: payload.display_name } })
  if (error) throw new Error(localizeError(error.message, 400))
  setCachedAuth(null, data.user)
  return getProfile()
}

export async function warmupProfileQuota() {
  return getProfile()
}

async function fetchProfileQuota(cacheKey) {
  if (cacheKey && pendingProfileQuotaRefreshes.has(cacheKey)) {
    return pendingProfileQuotaRefreshes.get(cacheKey)
  }
  const refresh = optionalRequest('/quotas/me', {}, { quota: null })
    .then((quota) => {
      const mine = quota?.quota || {}
      writeProfileQuotaCache(cacheKey, mine)
      return mine
    })
    .finally(() => {
      if (cacheKey) pendingProfileQuotaRefreshes.delete(cacheKey)
    })
  if (cacheKey) pendingProfileQuotaRefreshes.set(cacheKey, refresh)
  return refresh
}

function refreshProfileQuotaInBackground(cacheKey) {
  if (!cacheKey) return
  fetchProfileQuota(cacheKey).catch(() => null)
}

function profileQuotaCacheKey(user) {
  if (!user?.user_id || !user?.active_team_id) return ''
  return `${PROFILE_QUOTA_CACHE_PREFIX}:${user.active_team_id}:${user.user_id}`
}

function readProfileQuotaCache(cacheKey, options = {}) {
  if (!cacheKey || typeof localStorage === 'undefined') return null
  try {
    const payload = JSON.parse(localStorage.getItem(cacheKey) || 'null')
    if (!payload || !payload.quota) return null
    const age = Date.now() - Number(payload.cached_at || 0)
    if (age >= PROFILE_QUOTA_STALE_CACHE_TTL_MS) return null
    if (age >= PROFILE_QUOTA_CACHE_TTL_MS && options.allowStale !== true) return null
    return payload.quota
  } catch {
    return null
  }
}

function writeProfileQuotaCache(cacheKey, quota) {
  if (!cacheKey || typeof localStorage === 'undefined') return
  localStorage.setItem(cacheKey, JSON.stringify({
    cached_at: Date.now(),
    quota: quota || {},
  }))
}
